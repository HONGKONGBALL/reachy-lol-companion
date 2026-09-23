"""Measure the configured vision provider using two live, masked game frames."""
import asyncio
import json
import time
import uuid
import base64
import os
import argparse
from pathlib import Path
import httpx
from dotenv import load_dotenv
from reachy_lol.capture import Capture, windows
from reachy_lol.core import Frame
from reachy_lol.cloud import Cloud
from pydantic import BaseModel
from typing import Literal


class SafetyProbe(BaseModel):
    safe_context: Literal['unknown','risk','base_idle','safe_idle','postgame']
    safety_evidence: list[str]


async def main(model=None):
    load_dotenv()
    if model:os.environ['VISION_MODEL']=model
    usage=[]
    cloud=Cloud(usage.append)
    cloud.client.timeout=httpx.Timeout(45)
    original=cloud.request
    async def bounded(path,kind,**kwargs):
        if kind=='vision':
            kwargs['json']['max_completion_tokens']=250
            kwargs['json']['reasoning_effort']='none'
            for part in kwargs['json']['messages'][1]['content']:
                if part.get('type')=='image_url':
                    part['image_url']['detail']='low'
            kwargs['json']['messages'][0]['content']+=' 每类最多2条短句，输出精简，不重复描述。'
        return await original(path,kind,**kwargs)
    cloud.request=bounded
    capture=Capture()
    selected=[w for w in windows() if w['is_game']]
    if len(selected)!=1:
        raise RuntimeError('Exactly one real game window is required')
    capture.select(selected[0]['hwnd'])
    frames=[]
    for _ in range(2):
        jpeg=capture.grab()
        frames.append(Frame(uuid.uuid4().hex,time.monotonic(),jpeg,window_id=capture.hwnd,width=capture.width,height=capture.height))
        await asyncio.sleep(.6)
    try:
        content=[{'type':'text','text':json.dumps([{'id':f.id,'at':f.at} for f in frames])}]
        content.extend({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(f.jpeg).decode()}} for f in frames)
        cloud.request=original
        result=await cloud.safety(frames)
        report={'actual_game_frames':True,'result':result.model_dump(),'usage':usage}
    except Exception as exc:
        report={'actual_game_frames':True,'error':type(exc).__name__,'usage':usage}
    finally:
        await cloud.client.aclose()
    name='live-safety-reason-probe'+('-'+model if model else '')+'.json'
    Path('evidence',name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=['evomap-gpt-5.6-luna','evomap-gpt-5.6-terra','evomap-gpt-5.6-sol'])
    args=parser.parse_args()
    asyncio.run(main(args.model))
