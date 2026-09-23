import io
import threading
import time
import wave
import ctypes
import functools
import numpy as np
import sounddevice as sd
from .daemon_health import needs_live_probe, robot_health
from .acoustics import PlaybackReference
from .seat import seat_steps, seat_target, yaw_degrees
from .companion_motions import CompanionMotions, MOTIONS


def audio_apartment(fn):
    """WASAPI needs COM initialized on the thread opening/starting the stream."""
    @functools.wraps(fn)
    def wrapped(*args,**kwargs):
        hr=ctypes.windll.ole32.CoInitializeEx(None,2)
        try:
            return fn(*args,**kwargs)
        finally:
            if hr in (0,1):
                ctypes.windll.ole32.CoUninitialize()
    return wrapped


def audio_devices():
    hosts = sd.query_hostapis()
    return [dict(id=i, name=d['name'], inputs=d['max_input_channels'],
                 outputs=d['max_output_channels'], rate=d['default_samplerate'],
                 host=hosts[d['hostapi']]['name'],
                 key=hosts[d['hostapi']]['name']+'::'+d['name']) for i,d in enumerate(sd.query_devices())
            if 'reachy mini audio' in d['name'].lower()]


def choose_device(direction, selection=None):
    key = 'inputs' if direction == 'input' else 'outputs'
    candidates = [d for d in audio_devices() if d[key] > 0]
    if selection is not None:
        candidates=[d for d in candidates if d['key']==selection]
        if len(candidates)!=1:
            raise ValueError('所选 Reachy 音频设备已离线或名称不唯一，请在设备面板重新选择')
    if not candidates:
        raise RuntimeError(f'Reachy Mini Audio {direction} device unavailable; no PC fallback')
    candidates.sort(key=lambda d: ('WASAPI' not in d['host'], 'MME' not in d['host']))
    return candidates[0]


def sapi_wav(text):
    """Generate offline Mandarin speech in RAM; sound routed separately."""
    import comtypes
    from comtypes.client import CreateObject
    comtypes.CoInitialize()
    try:
        voice = CreateObject('SAPI.SpVoice')
        voices = voice.GetVoices()
        for i in range(voices.Count):
            item = voices.Item(i)
            if 'Huihui' in item.GetDescription():
                voice.Voice = item
                break
        stream = CreateObject('SAPI.SpMemoryStream')
        stream.Format.Type = 22  # 22,050 Hz, 16-bit mono
        voice.AudioOutputStream = stream
        voice.Rate = 1
        voice.Speak(text, 0)
        raw = bytes(stream.GetData())
        out = io.BytesIO()
        with wave.open(out, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(raw)
        return out.getvalue()
    finally:
        comtypes.CoUninitialize()


class Audio:
    def __init__(self):
        self.stream = None
        self.stop_event = threading.Event()
        self.playing = False
        self.volume = .35
        self.input_device = None
        self.output_device = None
        self.lock = threading.Lock()
        self.last_stop_ms = None
        self.reference = PlaybackReference()

    @audio_apartment
    def stop(self):
        started = time.monotonic()
        self.stop_event.set()
        with self.lock:
            if self.stream:
                self.stream.abort()
        self.last_stop_ms = round((time.monotonic()-started)*1000,2)

    @audio_apartment
    def play(self, wav_bytes, valid=lambda: True, on_first=None):
        device = choose_device('output',self.output_device)
        with wave.open(io.BytesIO(wav_bytes),'rb') as wav:
            if wav.getsampwidth() != 2:
                raise ValueError('Expected PCM16 WAV')
            rate, channels = wav.getframerate(), wav.getnchannels()
            if rate <= 0 or channels not in (1,2) or wav.getnframes()/rate > 15:
                raise ValueError('Speech WAV exceeds the 15-second bound or has invalid channels')
            samples = np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype('float32')/32768
            samples = samples.reshape(-1,channels)
        target_rate = int(device['rate'])
        if rate != target_rate:
            samples = np.stack([np.interp(np.arange(round(len(samples)*target_rate/rate))*rate/target_rate,
                                          np.arange(len(samples)),samples[:,c]) for c in range(channels)],axis=1).astype('float32')
        if device['outputs'] >= 2 and channels == 1:
            samples = np.repeat(samples,2,axis=1)
            channels = 2
        self.stop_event.clear()
        if not valid():
            return {'status':'cancelled_before_play'}
        stream = sd.OutputStream(device=device['id'],samplerate=target_rate,channels=channels,
                                 dtype='float32',blocksize=round(target_rate*.02),latency='low')
        with self.lock:
            self.stream = stream
        first = None
        written_frames = 0
        try:
            stream.start()
            self.playing = True
            for offset in range(0,len(samples),round(target_rate*.02)):
                if self.stop_event.is_set() or not valid():
                    stream.abort()
                    break
                block=samples[offset:offset+round(target_rate*.02)]*self.volume
                self.reference.write(block,target_rate)
                stream.write(block)
                written_frames += len(block)
                if first is None:
                    first = time.monotonic()
                    if on_first:
                        on_first()
            else:
                stream.stop()
            return {'status':'interrupted' if self.stop_event.is_set() or not valid() else 'written_to_device',
                    'device':device['name'], 'first_write_monotonic':first,
                    'duration_s':round(len(samples)/target_rate,2),
                    'written_audio_s':round(written_frames/target_rate,3),
                    'audible_confirmation':'NOT_RUN'}
        finally:
            self.playing = False
            with self.lock:
                self.stream = None
            stream.close()

    @audio_apartment
    def record_probe(self, seconds=2):
        device = choose_device('input',self.input_device)
        rate = int(device['rate'])
        data = sd.rec(int(rate*seconds),samplerate=rate,channels=1,dtype='float32',
                      device=device['id'],blocking=True)
        return {'device':device['name'],'sample_rate':rate,'frames':len(data),
                'rms':float(np.sqrt(np.mean(data**2))),'peak':float(np.max(np.abs(data))),
                'raw_media_saved':False}, data, rate


class Robot:
    def __init__(self):
        self.mini = None
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.neutral = None
        self.neutral_antennas = None
        self.expressions = CompanionMotions()

    def connect(self):
        from reachy_mini import ReachyMini
        if self.mini is None:
            import httpx
            with httpx.Client(trust_env=False,timeout=2) as client:
                status=client.get('http://127.0.0.1:8000/api/daemon/status').json()
                telemetry=None
                if needs_live_probe(status):
                    response=client.get('http://127.0.0.1:8000/api/state/full?with_head_joints=true')
                    response.raise_for_status()
                    telemetry=response.json()
            ready,reason=robot_health(status,telemetry)
            if not ready:
                raise RuntimeError(reason)
            self.mini = ReachyMini(media_backend='no_media', connection_mode='localhost_only',automatic_body_yaw=False)
            self.neutral = self.mini.get_current_head_pose().copy()
            self.neutral_antennas = np.array(self.mini.get_current_joint_positions()[1])
            self.mini.set_target(head=self.neutral,antennas=self.neutral_antennas)
            self.mini.enable_motors()

    def stop(self):
        self.cancelled.set()
        self.expressions.stop()

    def face_seat(self,yaw,valid=lambda:True):
        with self.lock:
            self.connect()
            self.cancelled.clear()
            start=self.mini.get_current_head_pose().copy()
            for pose in seat_steps(start,yaw):
                if self.cancelled.is_set() or not valid():
                    self.neutral=self.mini.get_current_head_pose().copy()
                    return {'cancelled':True,'command_sent':True}
                self.mini.set_target(head=pose)
                time.sleep(.025)
            # Small bounded feedback correction for servo tracking error. Never
            # change pitch/roll/translation or exceed the configured yaw envelope.
            command=float(yaw)
            stable=0
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                if self.cancelled.is_set() or not valid():
                    self.neutral=self.mini.get_current_head_pose().copy()
                    return {'cancelled':True,'command_sent':True}
                measured=self.mini.get_current_head_pose().copy()
                error=float(yaw)-yaw_degrees(measured)
                stable=stable+1 if abs(error)<1 else 0
                if stable>=3:
                    self.neutral=measured
                    self.neutral_antennas=np.array(self.mini.get_current_joint_positions()[1])
                    return {'cancelled':False,'command_sent':True,'yaw_degrees':yaw_degrees(measured),
                            'target_yaw_degrees':float(yaw),'command_yaw_degrees':command}
                if abs(error)>=1:
                    command=float(np.clip(command+np.clip(error*.2,-.2,.2),
                                          max(-20,float(yaw)-4),min(20,float(yaw)+4)))
                    self.mini.set_target(head=seat_target(start,command))
                time.sleep(.025)
            raise RuntimeError('头部未到达设置方向，未保存；请检查本体状态')

    def move(self, motion='nod', valid=lambda: True):
        if motion not in MOTIONS:
            raise ValueError('Motion not in whitelist')
        if not valid():
            return {'status':'stopped','command_sent':False}
        if motion not in ('nod','tilt','neutral'):
            # Do not queue stale expression threads behind another motion.
            if not self.lock.acquire(blocking=False):
                return {'status':'busy','command_sent':False}
            try:
                if not valid():return {'status':'stopped','command_sent':False}
                self.connect()
                self.cancelled.clear()
                return self.expressions.play_from_worker(self.mini,motion,
                    lambda:valid() and not self.cancelled.is_set())
            finally:
                self.lock.release()
        from reachy_mini.utils import create_head_pose
        with self.lock:
            self.connect()
            self.cancelled.clear()
            began = time.monotonic()
            while time.monotonic()-began < 1.2:
                if self.cancelled.is_set() or not valid():
                    break
                progress = (time.monotonic()-began)/1.2
                angle = 5*np.sin(progress*2*np.pi) if motion != 'neutral' else 0
                pose = self.neutral.copy()
                rotation = create_head_pose(pitch=angle if motion=='nod' else 0,
                                            roll=angle if motion=='tilt' else 0,degrees=True)
                pose[:3,:3] = self.neutral[:3,:3] @ rotation[:3,:3]
                self.mini.set_target(head=pose,antennas=self.neutral_antennas+np.array([0.08,-0.08])*np.sin(progress*np.pi))
                time.sleep(.025)
            # Short bounded return to the session's resting pose.
            start_pose=self.mini.get_current_head_pose().copy()
            start_antennas=np.array(self.mini.get_current_joint_positions()[1])
            for alpha in np.linspace(0,1,8):
                pose=self.neutral.copy()
                pose[:3,:3]=(1-alpha)*start_pose[:3,:3]+alpha*self.neutral[:3,:3]
                u,_,v=np.linalg.svd(pose[:3,:3])
                pose[:3,:3]=u@v
                self.mini.set_target(head=pose,antennas=(1-alpha)*start_antennas+alpha*self.neutral_antennas)
                time.sleep(.02)
            return {'motion':motion,'cancelled':self.cancelled.is_set(),'command_sent':True,
                    'physical_confirmation':'NOT_RUN'}

    def close(self):
        self.stop()
        with self.lock:
            if self.mini:
                # Daemon was started with --no-media; do not reacquire any camera.
                mini=self.mini
                self.mini=None
                self.neutral=self.neutral_antennas=None
                try:
                    mini.media_manager.close()
                finally:
                    mini.client.disconnect()
