import asyncio
import time
from unittest.mock import AsyncMock
from reachy_lol.runtime import Runtime
from reachy_lol.core import Frame, Events
from reachy_lol.cloud import Reply


def packet(at, events=()):
    return {'gameData':{'gameTime':at},'events':{'Events':list(events)},
            'activePlayer':{'riotId':'owner#CN','championStats':{'currentHealth':500,'maxHealth':1000}},
            'allPlayers':[{'riotId':'owner#CN','championName':'Qiyana','team':'ORDER'}]}


def kill(id=1,at=10,owner=True):
    return {'EventID':id,'EventTime':at,'EventName':'ChampionKill',
            'KillerName':'owner' if owner else 'teammate','VictimName':'enemy'}


def test_reconnect_baseline_and_unique_owner_events_only(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        try:
            fresh,_=r.events.ingest(packet(10,[kill()]))
            r.identity=r.identities.update(packet(10),r.events.match_id)
            r.queue_kill_reactions(fresh)
            assert r.event_reactions.empty()
            fresh,_=r.events.ingest(packet(11,[kill(),kill(2,11),kill(3,11,False)]))
            r.queue_kill_reactions(fresh)
            assert r.event_reactions.qsize()==1
            assert r.event_reactions.get_nowait()[3]['EventID']==2
            r.events.connected=False
            fresh,_=r.events.ingest(packet(12,[kill(4,12)]))
            assert not fresh
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_kill_reaction_has_its_own_short_output_gate(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=r.gate.robot_ready=True
        r.gate.game_present=True;r.gate.robot_at=r.game_at=10
        r.capture_valid=True;r.buffer.add(Frame('f',10,b'pixels'))
        try:
            assert not r.gate.allowed(10)  # No slow base/idle vision result.
            assert r.kill_reaction_allowed(10)
            r.gate.quiet=True
            assert not r.kill_reaction_allowed(10)
            r.gate.quiet=False;r.gate.owner_speaking=True
            assert not r.kill_reaction_allowed(10)
            assert r.kill_reaction_allowed(10,detected_at=6)  # VAD noise cannot starve verified events.
            r.gate.owner_speaking=False
            assert r.kill_reaction_allowed(10)
            assert not r.kill_reaction_allowed(12)  # Stale API/frame still blocks.
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_duplicate_kill_cheer_is_rewritten_instead_of_silently_dropped():
    from reachy_lol.cloud import Cloud, EventReply
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(side_effect=[
            EventReply(text='漂亮，又拿下一个！',motion='nod',evidence=['e']),
            EventReply(text='这次击杀收到了，给你鼓个掌！',motion='nod',evidence=['e'])])
        try:
            reply=await c.event_reply('aqi',[dict(kill(),event_key='e')],['漂亮，又拿下一个！'],{})
            assert reply.text=='这次击杀收到了，给你鼓个掌！'
            assert c.structured.await_count==2
        finally:await c.client.aclose()
    asyncio.run(run())


def test_bad_kill_rewrite_is_reported_not_silently_ignored():
    from reachy_lol.cloud import Cloud, EventReply
    import pytest
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(return_value=EventReply(text='漂亮，又拿下一个！',motion='nod',evidence=['e']))
        try:
            with pytest.raises(ValueError,match='仍重复'):
                await c.event_reply('aqi',[dict(kill(),event_key='e')],['漂亮，又拿下一个！'],{})
            assert c.structured.await_count==2
        finally:await c.client.aclose()
    asyncio.run(run())


def test_event_drafts_without_waiting_for_vision_and_respects_preferences(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.identity=r.identities.update(packet(10),r.events.match_id)
        r.cloud.event_reply=AsyncMock(return_value=Reply(text='漂亮，又拿下一个！',motion='nod',evidence=['e']))
        e=dict(kill(),event_key='e',match_id=r.events.match_id)
        r.preferences.events['kill'].enabled=False
        r.queue_kill_reactions([e]);assert r.event_reactions.empty()
        r.preferences.events['kill'].enabled=True
        r.queue_kill_reactions([e])
        task=asyncio.create_task(r.event_reaction_loop())
        try:
            async def ready():
                while not r.pending:await asyncio.sleep(.01)
            await asyncio.wait_for(ready(),2)
            assert r.pending[0].purpose=='kill_reaction'
            assert r.pending[0].evidence==['e'] and r.latest is None
            assert r.cloud.event_reply.await_count==1
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_stop_during_event_generation_discards_late_result(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.identity=r.identities.update(packet(10),r.events.match_id)
        async def delayed(*args):
            r.gate.invalidate('manual stop')
            return Reply(text='漂亮，又拿下一个！',motion='nod',evidence=['e'])
        r.cloud.event_reply=delayed
        r.queue_kill_reactions([dict(kill(),event_key='e')])
        task=asyncio.create_task(r.event_reaction_loop())
        try:
            await asyncio.sleep(.6)
            assert not r.pending
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_verified_kill_reaches_playback_without_visual_idle_and_is_not_cut_by_echo(tmp_path):
    from reachy_lol.core import Candidate
    async def run():
        r=Runtime(tmp_path);now=time.monotonic()
        r.gate.running=r.gate.robot_ready=True;r.gate.game_present=True
        r.gate.robot_at=r.game_at=now;r.capture_valid=True
        r.buffer.add(Frame('f',now,b'pixels'))
        r.pending.append(Candidate('漂亮，又拿下一个！',r.role,r.gate.epoch,now,['e'],True,'nod',purpose='kill_reaction'))
        r.cloud.tts=AsyncMock(return_value=b'synthetic')
        r.motion_safe=lambda *args:None
        loop=asyncio.get_running_loop();played=asyncio.Event()
        def play(wav,valid,on_first):
            assert valid()
            on_first();r.gate.owner_speaking=True
            assert valid()  # Unclassified sound must not clip the cheer.
            loop.call_soon_threadsafe(played.set)
            return {'status':'written_to_device'}
        r.audio.play=play
        task=asyncio.create_task(r.speech_loop())
        try:
            await asyncio.wait_for(played.wait(),1)
            await asyncio.sleep(.02)
            assert r.conversation.completed_replies()==['漂亮，又拿下一个！']
            assert r.speech_candidate is None
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())
