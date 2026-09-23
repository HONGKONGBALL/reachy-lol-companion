"""Protocol integration tests only: synthetic frames, mock HTTP, no robot access."""
import asyncio
import io
import json
import time
import wave

import httpx
import pytest
from PIL import Image

from reachy_lol.core import Frame
from reachy_lol.runtime import Runtime


def synthetic_wav():
    output=io.BytesIO()
    with wave.open(output,'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b'\0\0'*1600)
    return output.getvalue()


async def exercise(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv('TTS_PROVIDER', 'openai')
    for kind in ('VISION', 'CHAT', 'ASR', 'TTS'):
        for suffix in ('BASE_URL', 'API_KEY'):
            monkeypatch.delenv(f'{kind}_{suffix}', raising=False)
    for key,value in {'MODEL_BASE_URL':'https://protocol-test.invalid/v1',
                      'MODEL_API_KEY':'synthetic-test-key','VISION_MODEL':'test-vision',
                      'CHAT_MODEL':'test-chat','TTS_MODEL':'test-tts','VOICE_AQI':'test-voice'}.items():
        monkeypatch.setenv(key,value)
    (tmp_path/'evidence').mkdir()
    runtime=Runtime(tmp_path)
    await runtime.cloud.client.aclose()
    calls=[]
    audio_writes=[]
    motions=[]
    started=asyncio.Event()
    release=asyncio.Event()
    source=io.BytesIO()
    Image.new('RGB',(16,16),'gray').save(source,'JPEG')
    now=time.monotonic()
    runtime.gate.running=True
    runtime.gate.robot_ready=True
    runtime.gate.robot_at=now
    runtime.gate.safe_since=now-3
    runtime.gate.last_local=now
    evidence_id='synthetic-frame-1'

    async def handler(request):
        body=json.loads(request.content)
        calls.append(body.get('model'))
        assert request.headers['authorization']=='Bearer synthetic-test-key'
        if body['model']=='test-vision':
            content=body['messages'][1]['content']
            assert content[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
            assert json.loads(content[0]['text'])['frames'][0]['id']==evidence_id
            result={'observations':[{'text':'合成测试观察','evidence':[evidence_id]}],
                    'inferences':[],'unknowns':[],'contribution':'测试内容','outcome':'未知',
                    'safe':True,'meaningful':True}
        elif body['model']=='test-chat':
            supplied=json.loads(body['messages'][1]['content'])
            assert supplied['situation']['observations'][0]['evidence']==[evidence_id]
            result={'text':'合成测试回应','motion':'nod','evidence':[evidence_id]}
        elif body['model']=='test-tts':
            assert body['input']=='合成测试回应'
            assert body['voice']=='test-voice'
            started.set()
            if scenario=='cancel_during_tts':
                await release.wait()
            if scenario=='tts_http_failure':
                return httpx.Response(503,json={'error':'synthetic failure'})
            return httpx.Response(200,content=synthetic_wav(),headers={'Content-Type':'audio/wav'})
        else:
            pytest.fail('Unexpected request')
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(result)}}],
                                       'usage':{'total_tokens':10}})

    def fake_play(data,valid,on_first):
        assert valid()
        assert data.startswith(b'RIFF')
        audio_writes.append(data)
        on_first()
        return {'status':'test_sink_only'}

    runtime.cloud.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runtime.audio.play=fake_play
    runtime.audio.stop=lambda:None
    runtime.motion_safe=lambda motion,valid:motions.append((motion,valid()))
    tasks=[asyncio.create_task(runtime.analysis_loop()),asyncio.create_task(runtime.speech_loop())]
    runtime.analysis.put_nowait((runtime.gate.epoch,[Frame(evidence_id,now,source.getvalue(),42)],[],{'name':'fixture-owner'}))
    try:
        await asyncio.wait_for(started.wait(),1)
        if scenario=='cancel_during_tts':
            await runtime.control('role','anao')
            release.set()
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            if scenario=='success' and any(row['kind']=='playback' for row in runtime.logs) and motions:
                break
            if scenario=='tts_http_failure' and runtime.state['speaker'].startswith('失败'):
                break
            if scenario=='cancel_during_tts' and len(runtime.usages)==3 and not runtime.active_jobs:
                break
            await asyncio.sleep(.01)
        assert calls==['test-vision','test-chat','test-tts']
        assert len(runtime.usages)==3
        if scenario=='success':
            assert len(audio_writes)==1
            assert runtime.logs[-1]['evidence']==[evidence_id]
            assert motions==[('nod',True)]
        else:
            assert not audio_writes and not motions
        if scenario=='tts_http_failure':
            assert runtime.usages[-1]['status']=='failed'
        assert runtime.analysis.empty()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await runtime.cloud.client.aclose()


@pytest.mark.parametrize('scenario',['success','cancel_during_tts','tts_http_failure'])
def test_frame_to_output_protocol(tmp_path,monkeypatch,scenario):
    asyncio.run(exercise(tmp_path,monkeypatch,scenario))
