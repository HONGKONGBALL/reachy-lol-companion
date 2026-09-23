import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from reachy_lol.core import Gate, Frame
from reachy_lol.runtime import Runtime


def packet(dead=True):
    return {'activePlayer':{'riotId':'owner#CN'},'allPlayers':[
        {'riotId':'owner#CN','championName':'Zed','isDead':dead,'respawnTimer':20},
        {'riotId':'enemy#CN','championName':'Ahri','isDead':True}],
        'gameData':{'gameTime':100}}


def test_fresh_respawn_is_chat_window_even_at_zero_hp_and_risky_visuals():
    g=Gate(running=True,robot_ready=True,robot_at=10,game_present=True,
           owner_dead=True,owner_dead_at=10,last_local=10,visual_safe=False)
    assert g.safe_since is None and g.allowed(10)
    g.owner_dead=False
    assert not g.allowed(10)
    g.owner_dead=True;g.owner_dead_at=8
    assert not g.allowed(10)
    g.owner_dead_at=10;g.quiet=True
    assert not g.allowed(10)
    g.quiet=False;g.paused=True
    assert not g.allowed(10)
    g.paused=False;g.last_spoken=9
    assert not g.allowed(10)
    assert g.allowed(10,False)


@pytest.mark.parametrize('dead,expected',[(True,True),(False,False),('true',True),(None,False)])
def test_life_state_requires_unique_verified_owner_not_dead_teammate(tmp_path,dead,expected):
    async def run():
        r=Runtime(tmp_path);data=packet(dead)
        try:
            r.identity=r.identities.update(data,r.events.match_id)
            r.update_owner_life(data,10)
            assert r.gate.owner_dead is expected
            r.identity={'source':'owner_reported','aliases':['owner#CN']}
            r.update_owner_life(packet(),11)
            assert not r.gate.owner_dead
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_death_support_reaches_audio_without_vision_or_chat_model(tmp_path):
    async def run():
        r=Runtime(tmp_path);now=time.monotonic();data=packet()
        r.identity=r.identities.update(data,r.events.match_id)
        r.update_owner_life(data,now)
        r.gate.running=r.gate.robot_ready=True;r.gate.game_present=True
        r.gate.robot_at=r.game_at=now;r.capture_valid=True
        r.buffer.add(Frame('fresh',now,b'frame'))
        r.gate.visual_safe=False;r.gate.last_spoken=now-5
        event={'EventName':'ChampionKill','VictimName':'owner','KillerName':'enemy','event_key':'death1'}
        r.cloud.tts=AsyncMock(return_value=b'audio');r.motion_safe=lambda *args:None
        loop=asyncio.get_running_loop();played=asyncio.Event()
        def play(wav,valid,on_first):
            assert valid();on_first();loop.call_soon_threadsafe(played.set)
            return {'status':'written_to_device'}
        r.audio.play=play
        task=None
        try:
            r.queue_death_reactions([event,event])
            assert len(r.pending)==1 and r.pending[0].evidence==['death1']
            task=asyncio.create_task(r.speech_loop())
            await asyncio.wait_for(played.wait(),1)
            r.cloud.tts.assert_awaited_once()
            r.update_owner_life(packet(False),time.monotonic())
            assert not r.death_reaction_allowed(time.monotonic(),False)
        finally:
            if task:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_death_preference_and_quiet_are_respected(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.identity=r.identities.update(packet(),r.events.match_id)
        event={'EventName':'ChampionKill','VictimName':'owner','event_key':'death1'}
        try:
            r.preferences.events['death'].enabled=False
            r.queue_death_reactions([event]);assert not r.pending
            r.preferences.events['death'].enabled=True;r.gate.quiet=True
            r.queue_death_reactions([event]);assert not r.pending
            r.gate.quiet=False
            r.queue_death_reactions([{**event,'VictimName':'enemy'}]);assert not r.pending
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
