import asyncio
import json
import time
import httpx
from reachy_lol.cloud import Cloud
from reachy_lol.model_config import ModelConfig
from reachy_lol.usage import input_scale,numeric_usage,record


def test_scale_and_usage_do_not_keep_media_or_text():
    sample={'json':{'messages':[{'content':[{'type':'text','text':'private text'},
        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,privatepixels'}}]}]},
        'files':{'file':('owner.wav',b'private recording','audio/wav')}}
    scale=input_scale(sample)
    assert scale=={'text_characters':12,'image_count':1,'audio_bytes':17}
    usage=numeric_usage({'total_tokens':100,'text':'private words','bad':float('nan'),
                         'details':{'cached_tokens':80,'transcript':'private speech'}})
    assert usage=={'total_tokens':100,'details':{'cached_tokens':80}}
    row=record(ModelConfig('https://provider.invalid/v1','private-key','m'),'vision',
               time.monotonic(),'ok',usage,input_scale=scale)
    assert row['provider']=='provider.invalid' and row['request_id']
    assert 'private' not in json.dumps(row)
    assert row['cost'] is None and row['cost_status']=='not_computed'


def test_cancelled_http_request_is_logged_as_cancelled(monkeypatch):
    async def run():
        monkeypatch.setenv('MODEL_BASE_URL','https://provider.invalid/v1')
        monkeypatch.setenv('MODEL_API_KEY','secret-test')
        monkeypatch.setenv('CHAT_MODEL','m')
        monkeypatch.delenv('CHAT_BASE_URL',raising=False)
        monkeypatch.delenv('CHAT_API_KEY',raising=False)
        rows=[];started=asyncio.Event()
        async def handler(request):
            started.set();await asyncio.Event().wait()
        c=Cloud(rows.append);await c.client.aclose()
        c.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        task=asyncio.create_task(c.request('chat/completions','chat',json={'messages':[]}))
        await started.wait();task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert len(rows)==1 and rows[0]['status']=='cancelled'
        assert 'secret-test' not in json.dumps(rows)
        await c.client.aclose()
    asyncio.run(run())
