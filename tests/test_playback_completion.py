"""A partial device write must not become a remembered complete utterance."""
import asyncio
import time
import pytest
from reachy_lol.core import Candidate
from reachy_lol.runtime import Runtime


@pytest.mark.parametrize('status',['written_to_device','interrupted'])
def test_only_completed_output_is_saved_as_spoken(tmp_path,status):
    async def run():
        r=Runtime(tmp_path)
        now=time.monotonic()
        r.gate.running=True
        r.gate.robot_ready=True
        r.gate.robot_at=r.gate.last_local=r.gate.visual_at=now
        r.gate.visual_safe=True
        r.gate.safe_since=now-3
        r.pending.append(Candidate('整句测试内容','aqi',r.gate.epoch,now,[],False,'nod'))
        async def tts(*args):return b'mocked audio'
        def play(wav,valid,on_first):
            assert valid()
            on_first()
            return {'status':status,'first_write_monotonic':time.monotonic(),
                    'duration_s':4,'written_audio_s':4 if status=='written_to_device' else .04}
        r.cloud.tts=tts
        r.audio.play=play
        r.motion_safe=lambda *args:None
        task=asyncio.create_task(r.speech_loop())
        try:
            async def finished():
                while not any(row['kind']=='playback' for row in r.logs):
                    await asyncio.sleep(.005)
            await asyncio.wait_for(finished(),1)
            remembered=[m for m in r.memory_context() if m['kind']=='role_joke']
            if status=='written_to_device':
                assert remembered[0]['text']=='整句测试内容'
                assert '整段语音已写入' in r.state['speaker']
            else:
                assert not remembered
                assert '已中断' in r.state['speaker']
                assert '等待现场听觉确认' not in r.state['speaker']
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())
