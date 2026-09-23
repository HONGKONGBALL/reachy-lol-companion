"""Local WebRTC AEC3 using only this app's speaker output as reference."""
from collections import deque
import threading
import time
import numpy as np
from pywebrtc_audio import AudioProcessor


class PlaybackReference:
    def __init__(self):
        self.blocks=deque(maxlen=100)
        self.lock=threading.Lock()
        self.next_at=0.0

    def clear(self):
        with self.lock:
            self.blocks.clear()
            self.next_at=0.0

    def write(self, samples, rate, at=None):
        at=time.monotonic() if at is None else at
        mono=np.asarray(samples,dtype=np.float32)
        if mono.ndim==2:
            mono=mono.mean(axis=1)
        with self.lock:
            # Blocking writes can fill the device buffer ahead of the clock.
            start=max(at,self.next_at)
            self.blocks.append((start,rate,mono.copy()))
            self.next_at=start+len(mono)/rate
            while self.blocks and self.blocks[0][0]<at-2:
                self.blocks.popleft()

    def read(self, at, count, rate):
        result=np.zeros(count,dtype=np.float32)
        times=at+np.arange(count)/rate
        with self.lock:
            while self.blocks and self.blocks[0][0]<at-2:
                self.blocks.popleft()
            for start,source_rate,data in self.blocks:
                mask=(times>=start)&(times<start+len(data)/source_rate)
                if mask.any():
                    result[mask]=np.interp((times[mask]-start)*source_rate,np.arange(len(data)),data)
        return result


class SpeechFrontEnd:
    def __init__(self, rate, reference):
        self.rate=rate
        self.reference=reference
        self.metrics={}
        self.processor=AudioProcessor(sample_rate=rate,echo_cancellation=True,
            noise_suppression=True,high_pass_filter=True,auto_gain_control=False,
            ns_level=2,stream_delay_ms=20)

    def process(self, samples, at):
        mono=np.asarray(samples,dtype=np.float32).reshape(-1)
        reference=self.reference.read(at,len(mono),self.rate)
        clean=self.processor.process(mono,reference)
        probability=float(self.processor.speech_probability)
        rms=float(np.sqrt(np.mean(clean**2)))
        self.metrics={'input_rms':round(float(np.sqrt(np.mean(mono**2))),6),
                      'clean_rms':round(rms,6),
                      'reference_rms':round(float(np.sqrt(np.mean(reference**2))),6),
                      'speech_probability':round(probability,4)}
        speech=probability>=.65 and rms>=.004
        return clean.reshape(-1,1),speech,probability


class UtteranceSegmenter:
    """20 ms frames, 4/5 onset, 600 ms tail, bounded 12 s utterances."""
    def __init__(self):
        self.pre=deque(maxlen=10)
        self.votes=deque(maxlen=5)
        self.frames=[]
        self.voiced=0
        self.silence=0
        self.last_metrics={}

    def feed(self, frame, speech):
        started=False
        if not self.frames:
            self.pre.append(frame)
            self.votes.append(bool(speech))
            if sum(self.votes)<4:
                return False, None, False
            self.frames=list(self.pre)
            self.voiced=sum(self.votes)
            self.silence=0
            self.pre.clear();self.votes.clear()
            started=True
        else:
            self.frames.append(frame)
            self.voiced+=int(speech)
            self.silence=0 if speech else self.silence+1
        if self.silence>=30 or len(self.frames)>=600:
            self.last_metrics={'voiced_ms':self.voiced*20,
                               'speech_ratio':round(self.voiced/max(1,len(self.frames)-self.silence),3)}
            completed=np.concatenate(self.frames) if self.voiced>=8 else None
            self.frames=[];self.voiced=0;self.silence=0
            return started,completed,True
        return started,None,False
