import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from reachy_lol.cloud import Cloud, OwnerTurn, Reply
from reachy_lol.conversation import name_call
from reachy_lol.runtime import Runtime


@pytest.mark.parametrize('text,name,expected',[
    ('默默！','默默',(True,'')),
    ('嘿，默默，默默！','阿栖',(True,'')),
    ('小桃，金身是什么？','小桃',(True,'金身是什么')),
    ('我在默默打游戏','默默',(False,'我在默默打游戏')),
    ('队友说默默别说话','默默',(False,'队友说默默别说话')),
])
def test_vocative(text,name,expected):
    assert name_call(text,name)==expected


@pytest.mark.parametrize('in_game',[True,False,None])
def test_name_only_reaches_audio_during_combat_quiet_and_cooldown(tmp_path,in_game):
    async def run():
        r=Runtime(tmp_path);now=time.monotonic()
        r.gate.running=r.gate.robot_ready=r.gate.quiet=True
        r.gate.robot_at=now;r.gate.game_present=in_game
        r.gate.visual_safe=False;r.gate.safe_since=None;r.gate.last_spoken=now
        r.cloud.owner_turn=AsyncMock();r.cloud.asr=AsyncMock(return_value='默默！')
        r.cloud.tts=AsyncMock(return_value=b'synthetic');r.motion_safe=lambda *args:None
        loop=asyncio.get_running_loop();played=asyncio.Event()
        def play(wav,valid,on_first):
            assert valid();on_first();loop.call_soon_threadsafe(played.set)
            return {'status':'written_to_device'}
        r.audio.play=play
        task=None
        try:
            # Previously the same short response was rejected as canned/repeated.
            r.conversation.remember('assistant','在呢，你说。')
            await r.owner_audio(b'speech',r.gate.epoch)
            assert r.pending[0].purpose=='name_call'
            task=asyncio.create_task(r.speech_loop())
            await asyncio.wait_for(played.wait(),1)
            r.cloud.owner_turn.assert_not_awaited()
            r.cloud.tts.assert_awaited_once()
            assert r.cloud.tts.call_args.args[0]=='在呢，你说。'
            r.gate.paused=True
            assert not r.dialogue_allowed(time.monotonic())
        finally:
            if task:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_named_question_bypasses_semantic_attribution_but_uses_answer_model():
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(return_value=OwnerTurn(action='respond',
            reply=Reply(text='金身就是中娅沙漏，主动效果可以短暂无敌。',motion='neutral',evidence=[])))
        try:
            result=await c.owner_turn('aqi','默默，金身是什么？',None,[],{},
                                      {'name':'默默'},{'input_source':'microphone'})
            assert result.action=='respond'
            assert c.structured.call_args.args[-1] is OwnerTurn
        finally:await c.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('result',[OwnerTurn(action='ignore'),OwnerTurn(action='respond'),RuntimeError('offline')])
def test_named_question_gets_acknowledgement_if_model_cannot_answer(tmp_path,result):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.cloud.owner_turn=AsyncMock(**({'side_effect':result} if isinstance(result,Exception) else {'return_value':result}))
        try:
            await r.owner_text('默默，这波怎么办？',audio_context={})
            assert len(r.pending)==1 and not r.pending[0].proactive
            assert r.pending[0].purpose=='name_call'
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_name_call_respects_pause_end_and_explicit_silence(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.cloud.owner_turn=AsyncMock()
        try:
            await r.owner_text('默默！')
            assert not r.pending
            r.gate.running=True;r.gate.paused=True
            await r.owner_text('默默！')
            assert not r.pending
            r.gate.paused=False
            await r.owner_text('默默，别说话')
            assert r.gate.quiet and not r.pending
            r.cloud.owner_turn.assert_not_awaited()
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
