import asyncio
import json
import time
from unittest.mock import AsyncMock
from reachy_lol.cloud import Situation, Claim, Reply
from reachy_lol.core import Frame
from reachy_lol.runtime import Runtime


def test_continued_process_is_not_spoken_twice_and_trace_contains_no_reply(tmp_path):
    async def run():
        r=Runtime(tmp_path)
        now=time.monotonic()
        r.gate.running=True
        r.gate.robot_ready=True
        r.gate.robot_at=r.gate.last_local=now
        r.gate.safe_since=now-3
        r.audio.stop=lambda:None
        r.motion_safe=lambda *args:None
        r.cloud.tts=AsyncMock(return_value=b'synthetic-wav')
        r.cloud.reply=AsyncMock(return_value=Reply(text='private synthetic response',motion='nod',evidence=['f1']))
        writes=[]
        def play(data,valid,on_first):
            assert valid()
            on_first()
            assert valid()  # Marking spoken must not cancel the same playback.
            writes.append(data)
            return {'status':'test_sink_only'}
        r.audio.play=play
        async def analyze(frames,events,identity,owner_context,previous):
            current=frames[-1].id
            return Situation(observations=[Claim(text='门口持续牵制',evidence=[current])],
                inferences=[],unknowns=[],contribution='争取空间',outcome='未结束',safe=True,meaningful=True,
                continuation_of=previous['episode_id'] if previous else None,
                continuity_evidence=['f1','f2'] if previous else [])
        r.cloud.analyze=analyze
        tasks=[asyncio.create_task(r.analysis_loop()),asyncio.create_task(r.speech_loop())]
        async def until(predicate):
            deadline=time.monotonic()+1
            while not predicate():
                assert time.monotonic()<deadline
                await asyncio.sleep(.005)
        try:
            r.analysis.put_nowait((r.gate.epoch,[Frame('f1',now-.1,b'a')],[],None))
            await until(lambda:len(writes)==1)
            r.analysis.put_nowait((r.gate.epoch,[Frame('f2',now,b'b')],[],None))
            await until(lambda:len([x for x in r.logs if x['kind']=='episode_decision'])==2)
            assert len(r.episodes.items)==1 and r.episodes.active.spoken
            assert r.cloud.reply.await_count==1 and len(writes)==1 and not r.pending
            trace=(tmp_path/'evidence'/'decisions.jsonl').read_text(encoding='utf8')
            assert 'private synthetic response' not in trace
            records=[json.loads(line) for line in trace.splitlines()]
            decision=next(x for x in records if x['kind']=='episode_decision')
            assert decision['summary']['observations'][0]=={'summary':'门口持续牵制','evidence':['f1']}
            assert decision['summary']['source']=='model_analysis_unverified'
            playback=next(x for x in records if x['kind']=='playback')
            assert playback['episode_id']==r.episodes.active.id
            assert records[-1]['merged'] is True
            await r.control('end')
            assert not r.episodes.summaries()
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())
