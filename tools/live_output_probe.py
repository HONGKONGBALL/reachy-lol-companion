"""Bounded real game-to-robot output trial. Microphone stays disabled.

Uses the production capture, identity, safety, TTS and hardware code unchanged.
This is not a natural dialogue or contribution-feedback acceptance test.
"""
import asyncio
import json
import re
import time
import argparse
from pathlib import Path
import httpx
from dotenv import load_dotenv
from reachy_lol.capture import windows
from reachy_lol.runtime import Runtime


async def main(isolate_safety=False):
    load_dotenv()
    root=Path.cwd()
    async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
        page=await client.get('http://127.0.0.1:8768/')
        token=re.search(r'name="demo-token" content="([^"]+)"',page.text).group(1)
        state=(await client.get('http://127.0.0.1:8768/api/state',headers={'x-demo-token':token})).json()
        if state['running'] or state['playing']:
            raise RuntimeError('The main app is active; do not run concurrent robot sessions')
    selected=[w for w in windows() if w['is_game']]
    if len(selected)!=1:raise RuntimeError('Exactly one real game is required')
    r=Runtime(root)
    configured=r.cloud.configured
    r.cloud.configured=lambda kind='vision':False if kind=='asr' else configured(kind)
    report={'mode':'actual_game_output_only','microphone_enabled':False,
            'audible_confirmation':'NOT_RUN','natural_dialogue':'NOT_RUN',
            'full_analysis_enabled':not isolate_safety}
    try:
        await r.boot()
        if isolate_safety:
            task=next(t for t in r.tasks if t.get_coro().__name__=='analysis_loop')
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        await r.control('connect')
        await r.control('window',selected[0]['hwnd'])
        await r.control('start')
        assert r.mic_thread is None
        started=time.monotonic();last_status=-1000
        while time.monotonic()-started<55:
            if time.monotonic()-last_status>=5:
                print(json.dumps({'elapsed_s':round(time.monotonic()-started),
                    'frames':len(r.buffer.frames),'gate':r.gate.reason,
                    'safety':r.state.get('vision_safety'),'playing':r.audio.playing},ensure_ascii=False),flush=True)
                last_status=time.monotonic()
            playback=[x for x in r.logs if x['kind']=='playback']
            if playback:
                report['playback']=playback[-1]
                await asyncio.sleep(1)
                break
            checks=[x for x in r.logs if x['kind']=='safety_check']
            if isolate_safety and checks and not checks[-1]['continuous']:
                break
            await asyncio.sleep(.2)
        report.update(state={k:v for k,v in r.state.items() if k not in ('last_heard','last_reply')},
            champion=(r.identity or {}).get('champion'),frames=len(r.buffer.frames),
            gate=r.gate.reason,logs=list(r.logs),requests=list(r.usages),
            microphone_thread_started=r.mic_thread is not None)
    except Exception as exc:
        report['error']=type(exc).__name__
    finally:
        await r.shutdown()
    report['result']=('OUTPUT_WRITTEN_AUDIBILITY_UNCONFIRMED' if
        report.get('playback',{}).get('status')=='written_to_device' else 'NOT_PASSED')
    path=root/'evidence'/'live-output-only-probe.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--isolate-safety',action='store_true')
    args=parser.parse_args()
    asyncio.run(main(args.isolate_safety))
