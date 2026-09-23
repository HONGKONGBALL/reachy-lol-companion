import asyncio
import time
from unittest.mock import AsyncMock,Mock
from reachy_lol.runtime import Runtime
from reachy_lol.core import Candidate
from reachy_lol.conversation import has_address_cue


def test_reported_speech_complaint_is_an_address_cue():
    assert has_address_cue('怎么你又不说话了呀说话呀。')
    assert has_address_cue('你怎么又不回答我了')
    assert not has_address_cue('全军出击')


def test_requested_answer_bypasses_waiting_game_comment_and_visual_risk(tmp_path):
    async def run():
        r=Runtime(tmp_path);now=time.monotonic()
        r.gate.running=r.gate.robot_ready=True;r.gate.robot_at=now
        r.gate.game_present=True;r.gate.visual_safe=False
        r.pending.append(Candidate('长点评',r.role,r.gate.epoch,now,[],True))
        r.pending.append(Candidate('金身就是中娅沙漏。',r.role,r.gate.epoch,now,[],False))
        r.cloud.tts=AsyncMock(return_value=b'synthetic');r.motion_safe=lambda *args:None
        loop=asyncio.get_running_loop();played=asyncio.Event()
        # Keep the event callback separate from the audio worker thread.
        def play(wav,valid,on_first):
            assert valid();on_first();loop.call_soon_threadsafe(played.set)
            return {'status':'written_to_device'}
        r.audio.play=play
        task=asyncio.create_task(r.speech_loop())
        try:
            await asyncio.wait_for(played.wait(),1)
            assert r.cloud.tts.call_args.args[0]=='金身就是中娅沙漏。'
            r.gate.paused=True
            assert not r.dialogue_allowed(time.monotonic())
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True);await r.cloud.client.aclose()
    asyncio.run(run())


def test_lost_game_frame_does_not_stop_direct_conversation(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.audio.playing=True
        direct=Candidate('具体回答',r.role,r.gate.epoch,time.monotonic(),[],False)
        r.speech_candidate=direct;r.pending.append(direct)
        r.pending.append(Candidate('主动点评',r.role,r.gate.epoch,time.monotonic(),[],True))
        r.audio.stop=Mock();r.robot.stop=Mock()
        try:
            await r.halt_game_commentary('游戏画面不可用')
            assert list(r.pending)==[direct]
            assert direct.valid(r.gate,r.role,time.monotonic())
            r.audio.stop.assert_not_called()
            await r.control('quiet')
            r.audio.stop.assert_called_once()
            assert not r.pending
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
