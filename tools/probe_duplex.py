"""Bounded real-device echo trial. No captured audio is persisted or uploaded."""
import json
import threading
import time
from pathlib import Path
import numpy as np
import sounddevice as sd
from reachy_lol.hardware import Audio, audio_apartment, choose_device, sapi_wav
from reachy_lol.acoustics import SpeechFrontEnd


@audio_apartment
def main():
    audio=Audio()
    device=choose_device('input')
    rate=int(device['rate'])
    wav=sapi_wav('这是回声测试，我正在说话，麦克风也在同时收听。')
    blocks=[]
    processed=[]
    frontend=SpeechFrontEnd(rate,audio.reference)
    def callback(data, frames, timing, status):
        stamp=time.monotonic()+timing.inputBufferAdcTime-timing.currentTime
        began_processing=time.perf_counter()
        clean,speech,probability=frontend.process(data[:,0],stamp)
        processed.append((stamp,speech,probability,float(np.sqrt(np.mean(clean**2))),
                          (time.perf_counter()-began_processing)*1000))
        blocks.append((stamp,data[:,0].copy(),str(status)))
    with sd.InputStream(device=device['id'],samplerate=rate,channels=1,
                        dtype='float32',blocksize=int(rate*.02),callback=callback):
        time.sleep(2)
        began=time.monotonic()
        result=audio.play(wav)
        ended=time.monotonic()
        time.sleep(1.2)
    noise=.003; utterance=False; voiced=0; silence=0; interrupted=0; uploads=0
    phase_rms={'baseline':[],'playback':[],'tail':[]}
    for stamp,data,status in blocks:
        rms=float(np.sqrt(np.mean(data**2)))
        phase='baseline' if stamp<began else 'playback' if stamp<=ended else 'tail'
        phase_rms[phase].append(rms)
        speech=rms>max(.012,noise*3)
        if not speech and not utterance: noise=.99*noise+.01*rms
        if speech:
            utterance=True;silence=0;voiced+=1
            if voiced==4: interrupted+=1
        elif utterance: silence+=1
        if utterance and silence>=30:
            uploads+=int(voiced>=8)
            utterance=False;silence=0;voiced=0
    report={'at':time.strftime('%Y-%m-%d %H:%M:%S'),'device':device['name'],
            'playback':result,'raw_media_saved':False,'microphone_uploaded':False,
            'input_stream_errors':sum(bool(s) for _,_,s in blocks),
            'current_vad_interrupt_triggers':interrupted,'current_vad_utterances':uploads,
            'incomplete_utterance':utterance,
            'phase_rms':{k:{'blocks':len(v),'median':float(np.median(v)),
                            'max':max(v)} for k,v in phase_rms.items() if v},
            'processed':{phase:{'speech_blocks':sum(s for _,s,_,_,_ in values),
                                'blocks':len(values),
                                'rms_median':float(np.median([r for _,_,_,r,_ in values])),
                                'probability_median':float(np.median([p for _,_,p,_,_ in values]))}
                         for phase,values in (
                             ('baseline',[v for v in processed if v[0]<began]),
                             ('playback',[v for v in processed if began<=v[0]<=ended]),
                             ('tail',[v for v in processed if v[0]>ended])) if values},
            'processing_max_ms':max(v[-1] for v in processed),
            'interpretation':'Single room trial; no speaker labels. Does not prove owner separation or barge-in.'}
    blocks.clear();wav=None
    Path('evidence/duplex-processed-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__': main()
