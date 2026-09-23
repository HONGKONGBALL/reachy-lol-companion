"""Ordinary incoming speech is not an interrupt command (no real media/devices)."""
import asyncio
import time
from unittest.mock import Mock, AsyncMock
import pytest
from reachy_lol.runtime import Runtime
from reachy_lol.core import Candidate
from reachy_lol.cloud import OwnerTurn, Reply


def ready(tmp_path):
    r=Runtime(tmp_path)
    r.gate.running=r.gate.robot_ready=True
    r.gate.robot_at=r.gate.game_presence_at=time.monotonic()
    r.gate.game_present=False
    r.audio.stop=Mock()
    r.robot.stop=Mock()
    r.motion_safe=lambda *args:None
    return r


def test_new_sound_keeps_generating_reply_and_existing_pending(tmp_path):
    async def run():
        r=ready(tmp_path);started=asyncio.Event();release=asyncio.Event()
        r.pending.append(Candidate('earlier','aqi',r.gate.epoch,time.monotonic(),[],False))
        async def reply(*args):
            started.set();await release.wait()
            return OwnerTurn(action='respond',reply=Reply(text='later',motion='nod',evidence=[]))
        r.cloud.owner_turn=reply
        task=asyncio.create_task(r.owner_text('hello'))
        try:
            await asyncio.wait_for(started.wait(),1)
            epoch=r.gate.epoch
            await r.begin_owner_turn()
            assert r.gate.epoch==epoch and not task.done()
            release.set();await asyncio.wait_for(task,1)
            assert [p.text for p in r.pending]==['earlier','later']
            r.audio.stop.assert_not_called();r.robot.stop.assert_not_called()
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('phase',['synthesis','playback'])
def test_new_speech_does_not_cancel_synthesis_or_playback(tmp_path,phase):
    async def run():
        r=ready(tmp_path);loop=asyncio.get_running_loop();played=asyncio.Event()
        r.pending.append(Candidate('answer','aqi',r.gate.epoch,time.monotonic(),[],False))
        async def tts(*args):
            if phase=='synthesis':await r.begin_owner_turn()
            return b'synthetic'
        def play(wav,valid,on_first):
            on_first()
            if phase=='playback':
                asyncio.run_coroutine_threadsafe(r.begin_owner_turn(),loop).result(1)
            assert valid()
            loop.call_soon_threadsafe(played.set)
            return {'status':'written_to_device','duration_s':1,'written_audio_s':1}
        r.cloud.tts=tts;r.audio.play=play
        task=asyncio.create_task(r.speech_loop())
        try:
            await asyncio.wait_for(played.wait(),1)
            r.audio.stop.assert_not_called();r.robot.stop.assert_not_called()
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_explicit_stop_bypasses_slow_earlier_asr(tmp_path):
    async def run():
        r=ready(tmp_path);started=asyncio.Event();release=asyncio.Event()
        async def asr(wav):
            if wav==b'old':
                started.set();await release.wait();return 'hello'
            return '别说了'
        r.cloud.asr=asr;r.owner_text=AsyncMock()
        old=asyncio.create_task(r.owner_audio(b'old',r.gate.epoch))
        await asyncio.wait_for(started.wait(),1)
        new=asyncio.create_task(r.owner_audio(b'stop',r.gate.epoch))
        try:
            async def stopped():
                while not r.gate.quiet:await asyncio.sleep(.001)
            await asyncio.wait_for(stopped(),1)
            r.audio.stop.assert_called_once()
            assert not old.done()
            release.set();await asyncio.wait_for(asyncio.gather(old,new),1)
            r.owner_text.assert_not_awaited()
        finally:
            old.cancel();new.cancel();await asyncio.gather(old,new,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_risk_and_explicit_control_still_invalidate_output(tmp_path):
    async def run():
        r=ready(tmp_path)
        try:
            r.gate.game_present=True;r.gate.owner_speaking=True
            assert not r.gate.allowed(time.monotonic(),False)
            candidate=Candidate('answer','aqi',r.gate.epoch,time.monotonic(),[],False)
            r.pending.append(candidate)
            await r.owner_text('请先安静一下')
            assert not r.pending and not candidate.valid(r.gate,r.role,time.monotonic())
            r.audio.stop.assert_called_once()
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
