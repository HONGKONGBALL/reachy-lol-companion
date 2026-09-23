"""No-match dialogue must work without letting hidden/unknown matches bypass risk checks."""
import asyncio
import time
from unittest.mock import Mock
import pytest
from reachy_lol.core import Gate,Candidate,Frame
from reachy_lol.runtime import Runtime


def outside_gate():
    return Gate(running=True,robot_ready=True,robot_at=10,game_present=False,game_presence_at=10)


def test_no_match_allows_only_owner_reply_without_game_frames():
    g=outside_gate()
    assert g.allowed(10,False)
    assert not g.allowed(10,True)
    g.quiet=True
    assert g.allowed(10,False)
    g.owner_speaking=True
    assert g.allowed(10,False)
    assert not g.allowed(10,True)
    g.owner_speaking=False;g.paused=True
    assert not g.allowed(10,False)


@pytest.mark.parametrize('presence',[True,None])
def test_active_or_unknown_game_still_requires_visual_safety(presence):
    g=outside_gate();g.game_present=presence
    assert not g.allowed(10,False)


def test_expired_absence_and_disconnected_robot_block_dialogue():
    g=outside_gate()
    assert not g.allowed(11.6,False)
    g.game_presence_at=11.6;g.robot_ready=False
    assert not g.allowed(11.6,False)


def test_start_without_window_opens_microphone(tmp_path):
    async def run():
        r=Runtime(tmp_path)
        r.gate.robot_ready=True;r.gate.robot_at=time.monotonic()
        r.cloud.configured=lambda kind:True
        r.start_mic=Mock()
        try:
            await r.control('start')
            assert r.gate.running and r.capture.hwnd is None
            r.start_mic.assert_called_once()
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_game_entry_cancels_lobby_reply_and_exit_discards_stale_facts(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.audio.stop=Mock()
        r.gate.running=True
        now=time.monotonic()
        try:
            await r.update_game_presence(False,now)
            candidate=Candidate('lobby reply','aqi',r.gate.epoch,now,[],False)
            r.pending.append(candidate)
            await r.update_game_presence(True,now+.1)
            assert not r.pending and candidate.epoch!=r.gate.epoch
            r.audio.stop.assert_called_once()
            r.capture.hwnd=42;r.capture_valid=True
            r.buffer.add(Frame('old',now,b'old'))
            r.latest={'observations':['old match']}
            r.gate.visual_safe=True
            await r.update_game_presence(False,now+.2)
            assert not r.buffer.frames and not r.capture_valid and r.latest is None
            assert r.capture.hwnd is None and not r.gate.visual_safe
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
