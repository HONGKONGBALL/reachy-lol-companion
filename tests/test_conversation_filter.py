import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from reachy_lol.conversation import ConversationContext, reply_problem
from reachy_lol.cloud import Cloud, OwnerTurn, AudioOwnerTurn, SpeechAttribution, Reply
from reachy_lol.runtime import Runtime


@pytest.mark.parametrize('text',['啊。','嗯嗯','哦','全军出击！','Double kill','感谢观看'])
def test_background_fragments_are_rejected(text):
    assert ConversationContext().rejection(text,10)


def test_short_answer_needs_an_actually_completed_question_and_expires():
    c=ConversationContext()
    c.remember('assistant','想聊聊刚才那波吗？','queued',10)
    assert c.rejection('好的',11)
    row=c.playback('想聊聊刚才那波吗？',12)
    assert c.rejection('好的',13)
    c.finish(row,True,14)
    assert c.rejection('好的',15) is None
    assert c.rejection('好的',35)
    interrupted=c.playback('你觉得呢？',16)
    c.finish(interrupted,False,17)
    assert c.rejection('好的',18)


def test_echo_is_tied_to_playback_and_preserves_a_real_followup():
    c=ConversationContext()
    c.remember('assistant','刚才那波确实可惜，想聊聊吗？','queued',10)
    assert c.rejection('刚才那波确实可惜',11) is None
    row=c.playback('刚才那波确实可惜，想聊聊吗？',12)
    assert c.rejection('刚才那波确实可惜',13)=='self_echo'
    assert c.rejection('为什么你说刚才那波可惜？',13) is None
    c.finish(row,False,14)
    assert c.rejection('刚才那波确实可惜',16)=='self_echo'
    assert c.rejection('刚才那波确实可惜',18) is None
    c.clear()
    assert not c.snapshot(19)['recent_dialogue']


@pytest.mark.parametrize('text',['我在。','我在我在','我听着呢。','主人，我哪都不去，就在你身边护着你。','我在，你想聊什么？'])
def test_canned_reassurance_does_not_reach_tts(text):
    assert reply_problem(text,[])


def test_repeated_answers_rejected_but_explicit_repeat_allowed():
    text='这次配合失误确实挺让人郁闷的。'
    assert reply_problem(text,[text])=='repeated_reply'
    assert reply_problem(text,[text],'没听清，再说一遍') is None
    assert reply_problem('我在想要不要换个话题。',[]) is None


def attribution(**changes):
    return SpeechAttribution(**dict(source='user',target='assistant',confidence=.95,
        evidence_quote='阿栖，你叫什么名字？',contextual_followup=False,**changes))


@pytest.mark.parametrize('changes',[
    {'source':'game_or_media'}, {'target':'teammates'}, {'confidence':.6},
    {'source':'uncertain'}, {'evidence_quote':'不在原句里'}, {'contextual_followup':True}])
def test_untrusted_routing_cannot_reply_or_execute_controls(changes):
    async def run():
        c=Cloud(lambda _:None)
        fields=dict(source='user',target='assistant',confidence=.95,
                    evidence_quote='阿栖，你叫什么名字？',contextual_followup=False)
        fields.update(changes)
        c.structured=AsyncMock(return_value=AudioOwnerTurn(action='end',evidence_quote='阿栖',
                                                         attribution=SpeechAttribution(**fields)))
        try:
            turn=await c.owner_turn('aqi','阿栖，你叫什么名字？',None,[],{}, {},
                                    {'input_source':'microphone','followup_window':False})
            assert turn.action=='ignore' and turn.reply is None
            assert c.structured.call_args.args[-1] is AudioOwnerTurn
        finally:await c.client.aclose()
    asyncio.run(run())


def test_repeated_model_output_has_one_bounded_rewrite():
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(side_effect=[
            AudioOwnerTurn(action='respond',attribution=attribution(),
                           reply=Reply(text='我在。',motion='neutral',evidence=[])),
            Reply(text='叫我阿栖就好，你想聊什么？',motion='neutral',evidence=[])])
        try:
            result=await c.owner_turn('aqi','阿栖，你叫什么名字？',None,[],{},{},
                                     {'input_source':'microphone'})
            assert result.reply.text.startswith('叫我阿栖')
            assert c.structured.await_count==2
        finally:await c.client.aclose()
    asyncio.run(run())


def test_bad_rewrite_does_not_fall_back_to_a_canned_response():
    async def run():
        c=Cloud(lambda _:None)
        c.structured=AsyncMock(side_effect=[OwnerTurn(action='respond',reply=Reply(text='我在',motion='neutral',evidence=[])),
            Reply(text='在呢。',motion='neutral',evidence=[])])
        try:
            result=await c.owner_turn('aqi','你在吗',None,[],{},{})
            assert result.reply is None and c.structured.await_count==2
        finally:await c.client.aclose()
    asyncio.run(run())


def test_noise_does_not_upload_and_background_does_not_enter_memory(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.cloud.asr=AsyncMock(return_value='啊。')
        r.cloud.owner_turn=AsyncMock()
        try:
            await r.owner_audio(b'noise',r.gate.epoch,acoustic={'voiced_ms':100})
            r.cloud.asr.assert_not_awaited()
            await r.owner_audio(b'speech',r.gate.epoch)
            r.cloud.asr.assert_awaited_once()
            r.cloud.owner_turn.assert_not_awaited()
            assert not r.memory and not r.pending
            assert '啊' not in (tmp_path/'evidence'/'decisions.jsonl').read_text(encoding='utf8')
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_voice_resume_cannot_bypass_attribution(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.gate.quiet=True
        r.cloud.asr=AsyncMock(return_value='可以说话')
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='ignore'))
        try:
            await r.owner_audio(b'speech',r.gate.epoch)
            assert r.gate.quiet
            state=r.cloud.owner_turn.call_args.args[-1]
            assert state['input_source']=='microphone'
            assert not r.conversation.snapshot()['recent_dialogue']
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_dialogue_history_survives_game_memory_churn(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='respond',
            reply=Reply(text='你想给这个搭子取个什么名字？',motion='neutral',evidence=[])))
        try:
            await r.owner_text('我们聊聊名字吧')
            for _ in range(40):r.memory.append({'kind':'observed_fact'})
            r.cloud.owner_turn.return_value=OwnerTurn(action='ignore')
            await r.owner_text('第二句话')
            context=r.cloud.owner_turn.call_args.args[-1]
            assert context['recent_dialogue'][0]['text']=='我们聊聊名字吧'
            assert context['recent_replies']==['你想给这个搭子取个什么名字？']
            assert not context['followup_window']
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
