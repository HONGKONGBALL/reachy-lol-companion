"""Synthetic developer cases, real cloud latency; never counts as microphone acceptance."""
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv
from reachy_lol.cloud import Cloud
from reachy_lol.model_config import model_config


async def main():
    load_dotenv('.env')
    original=model_config('chat');asr=model_config('asr')
    assert urlsplit(asr.base_url).hostname=='dashscope.aliyuncs.com'
    cases=[('我今天打得很累，你陪我聊两句','respond'),
           ('我想专心一会儿，等会儿再聊','quiet'),
           ('不是让你停，我是在说刚才那个人','respond'),
           ('你的声音有点大，调小一些','volume_down')]
    rows=[]
    for provider,base,key,model in [('dashscope','https://dashscope.aliyuncs.com/compatible-mode/v1',asr.api_key,'qwen3.5-flash'),
                                   ('existing',original.base_url,original.api_key,original.model)]:
        os.environ.update(CHAT_BASE_URL=base,CHAT_API_KEY=key,CHAT_MODEL=model)
        c=Cloud(lambda _:None);request=c.request
        async def tuned(path,kind,**kwargs):
            if provider=='dashscope':kwargs['json'].update(enable_thinking=False,max_tokens=650)
            return await request(path,kind,**kwargs)
        c.request=tuned
        try:
            for text,expected in cases:
                start=time.monotonic();row={'provider':provider,'model':model,'synthetic_input':text,'expected':expected}
                try:
                    result=await c.owner_turn('aqi',text,None,[],{'fresh':False,'roster':[]},{}, {'running':True,'quiet':False,'volume':1.0})
                    row.update(action=result.action,passed=result.action==expected,reply=result.reply.model_dump() if result.reply else None)
                except Exception as exc:row.update(error=type(exc).__name__,passed=False)
                row['elapsed_ms']=round((time.monotonic()-start)*1000)
                rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        finally:await c.client.aclose()
    Path('evidence/dialogue-latency-comparison.json').write_text(json.dumps({'source':'synthetic_developer_cases','microphone_test':False,'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':asyncio.run(main())
