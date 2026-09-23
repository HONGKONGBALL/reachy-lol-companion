import asyncio
import time
from unittest.mock import AsyncMock
import pytest
from reachy_lol.identity import Identity,OwnerReport,ReportedFriend
from reachy_lol.cloud import Cloud,OwnerTurn
from reachy_lol.core import Frame
from reachy_lol.runtime import Runtime


def test_report_is_not_roster_mapping_and_clears_on_recovery():
    identity=Identity()
    owner=identity.report(OwnerReport(champion='诺手',team='蓝色方',
                          friends=[ReportedFriend(nickname='小李',champion='盲僧')]),'visual:session:1')
    assert owner['source']=='owner_reported' and not owner['aliases']
    assert not identity.fresh and not owner['verified_against_roster']
    identity.disconnect()
    assert identity.context()==owner
    assert identity.update({'activePlayer':{},'allPlayers':[]},'next') is None
    assert identity.reported_owner is None


def test_no_roster_report_requires_fields_in_owner_quote():
    async def run():
        cloud=Cloud(lambda _:None)
        cloud.structured=AsyncMock(return_value=OwnerTurn(action='report_identity',
            evidence_quote='这局我是诺手',reported_identity=OwnerReport(champion='诺手',team='蓝色方')))
        with pytest.raises(ValueError,match='没有的信息'):
            await cloud.owner_turn('aqi','这局我是诺手',None,[],{'fresh':False,'roster':[]},{})
        cloud.structured.return_value.reported_identity.team=None
        with pytest.raises(ValueError,match='现有名册'):
            await cloud.owner_turn('aqi','这局我是诺手',None,[],{'fresh':True,'roster':[{'name':'me'}]},{})
        result=await cloud.owner_turn('aqi','这局我是诺手',None,[],{'fresh':False,'roster':[]},{})
        assert result.action=='report_identity'
        await cloud.client.aclose()
    asyncio.run(run())


def test_report_needs_live_capture_and_pause_forgets_it(tmp_path):
    async def run():
        runtime=Runtime(tmp_path);runtime.audio.stop=lambda:None
        report=OwnerReport(champion='诺手')
        with pytest.raises(ValueError,match='前台'):
            await runtime.report_identity(report)
        runtime.gate.running=True;runtime.session='s';runtime.capture_valid=True
        runtime.buffer.add(Frame('f',time.monotonic(),b'test',None,1,0,20,20))
        await runtime.report_identity(report)
        assert runtime.identity['source']=='owner_reported'
        assert runtime.pending[0].purpose=='identity_confirmation'
        await runtime.control('pause')
        assert runtime.identity is None and runtime.identities.context() is None
        assert not any(m.get('identity') for m in runtime.memory)
        await runtime.cloud.client.aclose()
    asyncio.run(run())


def test_identity_question_is_bounded_and_uses_proactive_gate(tmp_path):
    async def run():
        runtime=Runtime(tmp_path);runtime.gate.running=True
        now=time.monotonic()
        assert runtime.queue_identity_question(now)
        candidate=runtime.pending[0]
        assert candidate.proactive and candidate.purpose=='identity_question'
        assert not runtime.gate.allowed(now,candidate.proactive)
        runtime.pending.clear()
        assert not runtime.queue_identity_question(now)
        runtime.identity_question_at-=91
        assert runtime.queue_identity_question(now)
        runtime.pending.clear();runtime.identity_question_at-=91
        assert not runtime.queue_identity_question(now)
        await runtime.cloud.client.aclose()
    asyncio.run(run())
