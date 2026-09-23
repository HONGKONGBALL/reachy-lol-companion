"""Conservative conversational addressing, not biometric speaker identification.

Only in-memory text/timing is retained. Acoustic hints cannot prove who spoke.
"""
from collections import deque
from difflib import SequenceMatcher
import re
import threading
import time


def compact(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', text.lower())


def name_call(text, name='默默'):
    """Recognize a spoken vocative, not a name mentioned inside a sentence.

    Return (addressed, remaining request). The default nickname stays callable
    when the display name changes. Echo/noise filtering still runs before this.
    """
    # ASR often writes the nickname as 陌陌/墨墨/莫莫. Treat these as
    # pronunciation aliases only in a vocative, never replace ordinary text.
    names=sorted({compact(n) for n in ('默默','陌陌','墨墨','莫莫','momo',name) if n},key=len,reverse=True)
    value=compact(text)
    value=re.sub(r'^(?:(?:嘿|喂|嗨|你好|哈喽|hello|hi|我靠|卧槽|我操|我草|我去|哎呀|哎哟|哎呦|诶|欸|哎|啊)[呀啊哦]*)+', '',value)
    pattern='(?:'+'|'.join(re.escape(n) for n in names)+')'
    match=re.match(pattern+'+',value)
    if not match:
        return False,value
    request=value[match.end():]
    return True,request


def has_address_cue(text, names=()):
    if any(name and name.lower() in text.lower() for name in ('阿栖','阿闹','reachy','机器人','搭子',*names)):
        return True
    return bool(re.search(r'你.{0,5}(?:说话|回答|回应|陪我)|说话[呀啊]|'
                          r'你(?:好|能|会|叫|觉得|认为|可以|为什么|怎么|知道|在|别|帮|给|说|听|看)|'
                          r'^(?:请|麻烦|帮我|给我|能不能|讲个|说个|我想听|安静|别说|闭嘴|停|结束陪玩|'
                          r'结束会话|暂停|关闭麦克风|恢复说话|继续陪我|可以说话)',text.strip()))


def is_game_vent(text):
    """Opt-in lively mode accepts game frustration without a wake word."""
    return bool(re.search(r'甩锅|不是我的锅|这(?:波|把|局).{0,8}(?:锅|离谱|气死|气炸|难受)|'
                          r'(?:队友|打野|辅助|上单|中单|AD|ad).{0,16}(?:送|不跟|没跟|不来|坑|挂机|死人|废物|干嘛|在干|离谱)|'
                          r'气死我|气炸了|凭什么怪我|怎么又怪我|都怪队友|队友.{0,6}有病',text))


def reply_problem(text, recent, owner_text=''):
    value=compact(text)
    if not value:
        return 'empty'
    if re.fullmatch(r'(?:我在|在呢){2,}',value):
        return 'empty_reassurance'
    if re.fullmatch(r'(?:主人)?(?:我在(?:呢|的|这里|这儿)?|在呢|我听着(?:呢)?|我在听(?:呢)?|你说(?:吧)?|你继续(?:说)?|我陪着你|我一直在)(?:呀|啊|哦|嗯|呢)*',value):
        return 'empty_reassurance'
    if re.match(r'^\s*(?:主人[，,、\s]*)?(?:我在(?:呢|的|这里|这儿)?|在呢|我听着(?:呢)?|我在听(?:呢)?)[，,。.!！\s]',text):
        return 'stock_opener'
    if re.fullmatch(r'(?:主人)?(?:我哪都不去|我不会离开你|我一直陪着你|我会一直陪着你)(?:就在你身边(?:护着你|陪着你)?|别担心|放心吧)*',value):
        return 'empty_reassurance'
    # Reject literal policing of game venting, but retain uncertainty for actual factual questions.
    vent = re.search(r'死人|废物|脑子|演员|气死|气炸|离谱|坑货|队友.{0,8}(?:不跟|没跟|不来|挂机)', owner_text)
    factual = re.search(r'确认|客观|核实|真的.{0,6}(?:死|挂机)|到底.{0,6}(?:死|挂机)|血量|装备效果', owner_text)
    if vent and not factual and re.search(r'不能确定|无法确定|不好判断|不能断定|不一定|未必|证据不足|别这么说|理性一点',text):
        return 'invalidating_owner_emotion'
    if not re.search(r'再说|重复|没听清|再讲|再念',owner_text):
        for previous in recent:
            old=compact(previous)
            if old and (value==old or (min(len(value),len(old))>=6 and
                                      SequenceMatcher(None,value,old).ratio()>=.88)):
                return 'repeated_reply'
    return None


class ConversationContext:
    def __init__(self):
        self.lock=threading.Lock()
        self.turns=deque(maxlen=16)
        self.outputs=deque(maxlen=8)

    def clear(self):
        with self.lock:
            self.turns.clear();self.outputs.clear()

    def remember(self, role, text, status='accepted', at=None):
        with self.lock:
            self.turns.append({'role':role,'text':text,'status':status,
                               'at':time.monotonic() if at is None else at})

    def playback(self, text, at=None):
        at=time.monotonic() if at is None else at
        with self.lock:
            row={'text':text,'start':at,'end':None}
            self.outputs.append(row)
        self.remember('assistant',text,'started',at)
        return row

    def finish(self, row, completed, at=None):
        with self.lock:
            row['end']=time.monotonic() if at is None else at
            row['completed']=completed

    def completed_replies(self):
        with self.lock:
            return [o['text'] for o in self.outputs if o.get('completed')]

    def snapshot(self, at=None):
        at=time.monotonic() if at is None else at
        with self.lock:
            turns=[dict(t) for t in self.turns]
            outputs=[dict(o) for o in self.outputs]
        # A queued or interrupted answer is not evidence the user heard a question.
        spoken=outputs[-1] if outputs and outputs[-1].get('completed') else None
        age=at-spoken['end'] if spoken else None
        recent=spoken is not None and 0<=age<=20
        return {'recent_dialogue':[{'role':t['role'],'text':t['text'],'status':t['status']}
                                    for t in turns if 0<=at-t['at']<=120],
                'recent_replies':[t['text'] for t in turns if t['role']=='assistant'][-6:],
                'followup_window':recent,
                'last_spoken_reply':spoken['text'] if recent else None,
                'awaiting_answer':bool(recent and re.search(r'[？?]|吗|呢|哪|什么|多少|是否',spoken['text']))}

    def rejection(self, text, at=None, acoustic=None):
        at=time.monotonic() if at is None else at
        value=compact(text)
        if not value:
            return 'empty_transcript'
        if acoustic and (acoustic.get('voiced_ms',1000)<240 or
                         acoustic.get('speech_ratio',1)<.18):
            return 'insufficient_speech'
        if re.fullmatch(r'[啊呃额唉哎噢哦嗯哈诶欸]+',value):
            return 'nonverbal_fragment'
        if value in ('好','好的','是','对','不是','不对','行','可以','不用','没事') and not self.snapshot(at)['awaiting_answer']:
            return 'unaddressed_short_fragment'
        if re.fullmatch(r'(?:欢迎来到英雄联盟|全军出击|敌军还有\w{0,5}到达战场|'
                        r'你已被击杀|你已经被击杀|我方防御塔已被摧毁|敌方防御塔已被摧毁|'
                        r'firstblood|doublekill|triplekill|quadrakill|pentakill|aced|defeat|victory|'
                        r'感谢观看|谢谢观看|请点赞关注|字幕由\w+提供)',value):
            return 'game_or_media'
        with self.lock:
            outputs=[dict(o) for o in self.outputs]
        for output in outputs:
            # Compare only against output actually sent to the device, including
            # interrupted speech; never against merely generated/queued replies.
            if at<output['start'] or (output['end'] is not None and at>output['end']+3):
                continue
            old=compact(output['text'])
            if value==old or (len(value)>=4 and len(value)<=len(old) and value in old) or (
                    min(len(value),len(old))>=6 and SequenceMatcher(None,value,old).ratio()>=.84):
                return 'self_echo'
        return None
