import asyncio
from unittest.mock import AsyncMock
import pytest
from reachy_lol.cloud import Cloud, OwnerTurn, Reply
from reachy_lol.runtime import Runtime


def runtime(tmp_path):
    r=Runtime(tmp_path)
    r.gate.running=True
    r.audio.stop=lambda:None
    return r


def test_immediate_stop_does_not_need_cloud(tmp_path):
    async def run():
        r=runtime(tmp_path)
        r.cloud.owner_turn=AsyncMock(side_effect=AssertionError('stop must be local'))
        await r.owner_text('请先安静一下。')
        assert r.gate.quiet
        r.cloud.owner_turn.assert_not_called()
        await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('text',['别安静，接着聊','队友刚才说“别说了”，气死我了','不是所有人都跟上了'])
def test_substrings_do_not_execute_or_delete_memory(tmp_path,text):
    async def run():
        r=runtime(tmp_path)
        fact={'kind':'observed_fact','match_id':r.events.match_id,'situation':{'old':'fact'}}
        r.memory.append(fact)
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='respond',reply=Reply(text='你是想继续聊刚才那件事吗？',motion='neutral',evidence=[])))
        await r.owner_text(text)
        assert not r.gate.quiet and fact in r.memory
        assert r.pending[0].text=='你是想继续聊刚才那件事吗？'
        r.cloud.owner_turn.assert_awaited_once()
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_semantic_correction_preserves_other_episodes_and_carries_source(tmp_path):
    async def run():
        r=runtime(tmp_path)
        current={'observations':[], 'inferences':[{'text':'守入口','evidence':['f']} ]}
        r.latest=current
        old={'kind':'observed_fact','match_id':r.events.match_id,'situation':{'old':'event'}}
        r.memory.extend([old,{'kind':'observed_fact','match_id':r.events.match_id,'situation':current}])
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='correct',evidence_quote='我只是顺路回家',
            reply=Reply(text='明白，是顺路回家。',motion='neutral',evidence=[])))
        await r.owner_text('我只是顺路回家')
        assert r.latest is None and old in r.memory
        assert not any(m.get('situation')==current for m in r.memory)
        assert r.memory[-1]['kind']=='correction' and r.memory[-1]['match_id']==r.events.match_id
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_role_switch_changes_voice_and_discards_old_reply(tmp_path):
    async def run():
        r=runtime(tmp_path)
        r.preferences.voice='velvet'
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='switch_role',evidence_quote='想听另外一位陪我'))
        old_epoch=r.gate.epoch
        await r.owner_text('想听另外一位陪我')
        assert r.role=='anao' and r.preferences.voice=='sparkle'
        assert r.gate.epoch>old_epoch and not r.pending
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_late_intent_after_end_cannot_change_next_session(tmp_path):
    async def run():
        r=runtime(tmp_path)
        async def delayed(*args):
            await r.control('end')
            return OwnerTurn(action='switch_role',evidence_quote='换个人')
        r.cloud.owner_turn=delayed
        await r.owner_text('换个人')
        assert r.role=='aqi' and not r.gate.running and not r.memory
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_control_requires_a_quote_from_the_current_owner_turn():
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(return_value=OwnerTurn(action='end',evidence_quote='结束陪玩'))
        with pytest.raises(ValueError):
            await c.owner_turn('aqi','刚才真紧张',None,[],{}, {})
        await c.client.aclose()
    asyncio.run(run())


def test_no_fact_sheet_means_no_fact_retraction():
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(return_value=OwnerTurn(action='correct',evidence_quote='不是让你停'))
        turn=await c.owner_turn('aqi','不是让你停，我是在说刚才那个人',None,[],{}, {})
        assert turn.action=='respond'
        await c.client.aclose()
    asyncio.run(run())
