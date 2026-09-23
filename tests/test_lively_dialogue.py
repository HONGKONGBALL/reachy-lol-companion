import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from reachy_lol.cloud import Cloud, OwnerTurn, Reply
from reachy_lol.core import Gate, Candidate
from reachy_lol.conversation import is_game_vent
from reachy_lol.runtime import Runtime


@pytest.mark.parametrize('text',['这些队友是死人吗，喊半天都不跟！','打野怎么又送了！','不是我的锅啊','气死我了'])
def test_lively_vent_without_name_is_addressed(text):
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(return_value=OwnerTurn(action='respond',
            reply=Reply(text='喊半天没人跟，确实够憋屈的。',motion='neutral',evidence=[])))
        try:
            assert is_game_vent(text)
            result=await c.owner_turn('aqi',text,None,[],{}, {'intensity':'chaos'},{'input_source':'microphone'})
            assert result.action=='respond' and result.reply
            assert c.structured.call_args.args[-1] is OwnerTurn
        finally:await c.client.aclose()
    asyncio.run(run())


def test_lively_risky_combat_reaches_playback(tmp_path):
    async def run():
        r=Runtime(tmp_path);now=time.monotonic()
        r.gate=Gate(running=True,robot_ready=True,robot_at=now,game_present=True,
                    relaxed=True,cooldown=8,last_local=now,visual_safe=False)
        r.pending.append(Candidate('这一波拿下了，漂亮！',r.role,r.gate.epoch,now,['event'],True,'neutral'))
        r.cloud.tts=AsyncMock(return_value=b'audio');r.motion_safe=lambda *args:None
        loop=asyncio.get_running_loop();played=asyncio.Event()
        def play(wav,valid,on_first):
            assert valid();on_first();assert valid()
            loop.call_soon_threadsafe(played.set)
            return {'status':'written_to_device'}
        r.audio.play=play
        task=asyncio.create_task(r.speech_loop())
        try:
            await asyncio.wait_for(played.wait(),1)
            r.gate.quiet=True
            assert not r.gate.allowed(time.monotonic())
            r.gate.quiet=False;r.gate.relaxed=False
            assert not r.gate.allowed(time.monotonic(),False)
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_rejected_lively_vent_still_queues_support(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.preferences.intensity='chaos';r.gate.relaxed=True
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='ignore'))
        try:
            await r.owner_text('队友为什么又送了啊',audio_context={})
            assert r.pending and not r.pending[0].proactive
            assert '憋屈' in r.pending[0].text
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_lively_vent_does_not_authorize_session_controls():
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(return_value=OwnerTurn(action='end',evidence_quote='队友'))
        try:
            turn=await c.owner_turn('aqi','队友说结束陪玩，他又送了',None,[],{},
                                    {'intensity':'chaos'},{'input_source':'microphone'})
            assert turn.action=='respond'
        finally:await c.client.aclose()
    asyncio.run(run())
