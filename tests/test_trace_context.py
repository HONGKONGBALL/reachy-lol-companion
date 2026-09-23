import asyncio
import time
from types import SimpleNamespace
from reachy_lol.usage import request_scope,record
from reachy_lol.trace import decision_summary


def test_dialogue_failures_do_not_persist_untrusted_exception_payload(tmp_path):
    from unittest.mock import AsyncMock
    from reachy_lol.runtime import Runtime
    async def run():
        r=Runtime(tmp_path)
        r.gate.running=True
        r.audio.stop=lambda:None
        r.cloud.owner_turn=AsyncMock(side_effect=ValueError('private transcript and model payload'))
        try:
            await r.owner_text('private current utterance')
            trace=(tmp_path/'evidence'/'decisions.jsonl').read_text(encoding='utf-8')
            assert 'private' not in trace
            row=r.logs[-1]
            assert row['error_code']=='unclassified' and row['stage']=='model_reply'
            assert row['turn_id']
            r.cloud.owner_turn=AsyncMock(side_effect=ValueError('控制意图缺少当前主人原句依据'))
            await r.owner_text('private current utterance')
            assert r.logs[-1]['error_code']=='control_quote_not_in_utterance'
            assert not r.pending
        finally:
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_concurrent_request_scopes_do_not_mix_turns_or_survive_scope():
    async def run():
        config=SimpleNamespace(base_url='https://example.com',model='test')
        async def request(turn,delay):
            with request_scope(session_id='s',turn_id=turn,phase='owner_dialogue'):
                await asyncio.sleep(delay)
                return record(config,'chat',time.monotonic(),'ok',{})
        rows=await asyncio.gather(request('old',.01),request('new',0))
        assert [x['turn_id'] for x in rows]==['old','new']
        assert 'turn_id' not in record(config,'chat',time.monotonic(),'ok',{})
    asyncio.run(run())


def test_fact_summary_is_bounded_anonymized_and_separates_inference():
    fact={'observations':[{'text':'private#id挡住入口','evidence':['f1']}],
          'inferences':[{'text':'可能争取空间','evidence':['f1']}],
          'unknowns':['不确定'], 'contribution':'x'*1000,'outcome':'未知',
          'meaningful':True,'safe':False,'owner_transcript':'must not persist'}
    summary=decision_summary(fact,{'aliases':['private#id']})
    assert summary['observations'][0]['summary']=='[玩家]挡住入口'
    assert summary['inferences'][0]['summary']=='可能争取空间'
    assert len(summary['contribution'])==180
    assert 'owner_transcript' not in summary
