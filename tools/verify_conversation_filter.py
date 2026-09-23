"""Bounded provider check using synthetic text; no microphone, TTS or motion."""
import asyncio
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from reachy_lol.cloud import Cloud
from reachy_lol.conversation import ConversationContext, reply_problem
from reachy_lol.model_config import model_config


async def main():
    load_dotenv()
    cloud=Cloud(lambda _:None)
    cases=[
        ('noise','啊。','ignore',None),
        ('announcer','全军出击！','ignore',None),
        ('team_command','打野来下路，先别打龙，等我到了再开。','ignore',None),
        ('team_question','你怎么不交闪现啊，AD你在干嘛？','ignore',None),
        ('media','欢迎收看今天的直播，喜欢的朋友点个关注。','ignore',None),
        ('self_talk','唉，又没补到这个炮车。','ignore',None),
        ('direct_name','阿栖，你叫什么名字，能陪我聊点什么？','respond',None),
        ('direct_feedback','阿栖，你别一直说我在我在，换点有内容的话聊。','respond',None),
        ('followup','就聊今天发生的趣事吧。','respond','你想聊游戏，还是聊今天发生的趣事？'),
        ('short_answer','好的','respond','你想听一个关于猫的小笑话吗？'),
        ('team_during_window','辅助快过来，别打龙了先撤退！','ignore','你想聊游戏，还是聊今天发生的趣事？'),
        ('general_question','你能给我讲一个猫的笑话吗？','respond',None),
    ]
    rows=[]
    try:
        for name,text,expected,question in cases:
            context=ConversationContext()
            if question:
                row=context.playback(question,time.monotonic()-3)
                context.finish(row,True,time.monotonic()-1)
            state={'input_source':'microphone',**context.snapshot()}
            rejected=context.rejection(text)
            started=time.monotonic()
            if rejected:
                row={'case':name,'action':'ignore','local_reason':rejected,'reply':None}
            else:
                turn=await cloud.owner_turn('aqi',text,None,[],{}, {},state)
                row={'case':name,'action':turn.action,'reply':turn.reply.text if turn.reply else None,
                     'attribution':turn.attribution.model_dump() if hasattr(turn,'attribution') else None}
            row.update(expected=expected,passed=row['action']==expected and
                       (expected!='respond' or bool(row['reply']) and not reply_problem(row['reply'],[],text)),
                       duration_ms=round((time.monotonic()-started)*1000))
            rows.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    finally:
        await cloud.client.aclose()
        report={'source':'synthetic_text_real_configured_chat_provider','microphone_tested':False,
                'provider':model_config('chat').base_url,'model':model_config('chat').model,
                'robot_audio_output':False,'cases':rows,'passed':sum(r['passed'] for r in rows),'total':len(cases)}
        Path('evidence/conversation-filter-provider.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if not all(r['passed'] for r in rows):
        raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
