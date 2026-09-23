import asyncio
import io
import json
import math
import os
import queue
import re
import threading
import time
import uuid
import wave
from collections import deque
from pathlib import Path
import httpx
import numpy as np
import sounddevice as sd
from .capture import Capture, windows, game_process_running
from .cloud import Cloud
from .core import Candidate, Events, Frame, FrameBuffer, Gate, boolean
from .hardware import Audio, Robot, audio_devices, choose_device, sapi_wav, audio_apartment
from .settings import Preferences, VOICE_ENV, VOICE_ROLE, EVENT_TYPES
from .identity import Identity, aliases
from .episodes import Episodes
from .daemon_health import needs_live_probe, robot_health
from .acoustics import SpeechFrontEnd, UtteranceSegmenter
from .conversation import ConversationContext, reply_problem, name_call, is_game_vent
from .match_research import research_match
from .long_memory import LongMemory
from .opgg import champion_build
from .visual_safety import VisualSafety
from .usage import request_scope
from .trace import decision_summary, dialogue_error_code


class Runtime:
    def __init__(self, root):
        self.root = Path(root)
        self.gate, self.buffer, self.events = Gate(), FrameBuffer(), Events()
        self.capture, self.audio, self.robot = Capture(), Audio(), Robot()
        self.cloud = Cloud(self.usage)
        self.role = 'aqi'
        self.memory = deque(maxlen=30)
        self.conversation = ConversationContext()
        self.match_knowledge = None
        self.research_task = None
        self.research_scope = None
        self.long_memory = LongMemory(self.root)
        self.build_task = None
        self.build_scope = None
        self.build_knowledge = None
        self.build_retry_at = 0
        self.logs = deque(maxlen=100)
        self.usages = deque(maxlen=2000)
        self.pending = deque(maxlen=3)
        self.analysis = asyncio.Queue(maxsize=1)
        self.safety_analysis = asyncio.Queue(maxsize=1)
        self.event_reactions = asyncio.Queue(maxsize=4)
        self.speech_candidate = None
        self.reacted_events = deque(maxlen=60)
        self.ready_announced = False
        self.facts_revision = 0
        self.tasks = []
        self.latest = None
        self.identity = None
        self.identity_questions=0
        self.identity_question_at=-1000
        self.identities = Identity()
        self.episodes = Episodes()
        self.capture_segment = 0
        self.capture_valid = False
        self.visual_safety=VisualSafety()
        self.game = None
        self.game_at = -1000
        self.health = None
        self.recent_events = []
        self.state = {'robot':'未检查','microphone':'未检查','speaker':'未检查',
                      'motion':'未检查','capture':'未选择','game_api':'未连接','cloud':'未配置'}
        self.mic_stop = threading.Event()
        self.mic_thread = None
        self.loop = None
        self.last_voice_at = -1000
        self.speaking = False
        self.session = None
        self.active_jobs = set()
        self.owner_task = None
        self.owner_tasks = set()
        self.owner_turn_lock = asyncio.Lock()
        self.usage_clear_before = -1
        self.clearing_data = False
        self.diagnostic_lock = asyncio.Lock()
        self.last_episode_at = -1000
        self.last_wait_reason = None
        self.preferences=Preferences()
        prefs_path=self.root/'preferences.json'
        if prefs_path.exists():
            try:
                self.preferences=Preferences.model_validate_json(prefs_path.read_text(encoding='utf8'))
            except ValueError:
                self.log('preferences_invalid')
        self.role=VOICE_ROLE.get(self.preferences.voice,'aqi')
        self.audio.volume=self.preferences.volume
        self.audio.input_device=self.preferences.input_device
        self.audio.output_device=self.preferences.output_device
        self.gate.cooldown={'chill':45,'normal':30,'chaos':8}[self.preferences.intensity]
        self.gate.relaxed=self.preferences.intensity=='chaos'
        history=self.root/'evidence'/'hardware.jsonl'
        if history.exists():
            for line in history.read_text(encoding='utf8').splitlines()[-20:]:
                try:
                    row=json.loads(line)
                    if row.get('kind')=='microphone' and row.get('frames',0)>0:
                        self.state['microphone']='上次实测已读取本体信号 · 当前未收听'
                    elif row.get('kind')=='audio' and row.get('status') in ('written_to_device','interrupted'):
                        self.state['speaker']='上次实测已写入本体设备 · 待听觉确认'
                    elif row.get('kind')=='motion' and row.get('command_sent'):
                        self.state['motion']='上次实测已执行动作指令 · 待现场确认'
                except (ValueError,TypeError):
                    pass

    def log(self, kind, **data):
        at=time.monotonic()
        self.logs.append({'time':time.strftime('%H:%M:%S'),'at':at,'kind':kind,**data})
        if kind in ('episode_decision','episode_candidate','candidate_wait','expired_candidate','playback','cancel',
                    'analysis_failed','asr_failed','dialogue_failed','speech_failed','safety_check','safety_failed','voice_onset',
                    'speech_rejected','reply_rejected','game_event','event_candidate','event_failed',
                    'match_research_ready','match_research_failed'):
            keys=('episode_id','revision','previous_episode_id','merged','evidence','source_at','expires_at',
                  'role','reason','status','first_write_monotonic','duration_s','purpose','summary',
                  'analysis_id','turn_id','input_finished_at','response_latency_ms','gate_reason','error','error_code','stage',
                  'safe','continuous','source_age_ms','written_audio_s',
                  'input_rms','clean_rms','reference_rms','speech_probability','during_playback','capture_delay_ms')
            record={'at':at,'kind':kind,'session_id':data.get('session_id',self.session),
                    **{k:data[k] for k in keys if k in data}}
            try:
                path=self.root/'evidence'/'decisions.jsonl'
                path.parent.mkdir(exist_ok=True)
                if path.exists() and path.stat().st_size>1024*1024:
                    path.replace(path.with_name('decisions.previous.jsonl'))
                with path.open('a',encoding='utf8') as output:
                    output.write(json.dumps(record,ensure_ascii=False)+'\n')
            except OSError as exc:
                self.logs.append({'time':time.strftime('%H:%M:%S'),'kind':'trace_failed','error':type(exc).__name__})

    def usage(self, record):
        if record.get('started_monotonic',-1)<=self.usage_clear_before:
            return
        record={'session_id':self.session,**record}
        self.usages.append(record)
        # No transcripts or media in the persistent usage journal.
        with (self.root/'evidence'/'usage.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n')

    def snapshot(self):
        self.gate.allowed(time.monotonic())
        if self.gate.respawning(time.monotonic()):
            self.state['vision_safety']='游戏接口已确认你在等待复活，可以聊天'
        elif self.gate.relaxed:
            self.state['vision_safety']='热闹模式：战斗中也会短回应，叫名字或吐槽直接接话'
        return dict(state=self.state,role=self.role,running=self.gate.running,paused=self.gate.paused,
                    quiet=self.gate.quiet,intensity=self.preferences.intensity,
                    gate=self.gate.reason,frames=len(self.buffer.frames),
                    analysis_waiting=self.analysis.qsize(),pending=len(self.pending),
                    identity=self.identity,identity_status=self.identities.snapshot(),situation=self.latest,
                    episodes=self.episodes.summaries(),logs=list(self.logs)[-20:],
                    usage_count=len(self.usages),playing=self.audio.playing,
                    recent_usage=list(self.usages)[-20:],volume=self.audio.volume,
                    stop_call_ms=self.audio.last_stop_ms,
                    cloud_configured={k:self.cloud.configured(k) for k in ('vision','chat','asr','tts')},
                    game_present=self.gate.game_present,
                    match_research=self.match_knowledge.summary() if self.match_knowledge else None,
                    equipment_memory=self.long_memory.summary(),
                    champion_build=self.build_knowledge,
                    expression_skills=self.robot.expressions.summary(),
                    devices=audio_devices(),windows=windows(),selected_window=self.capture.hwnd)

    def preferences_snapshot(self):
        return {'preferences':self.preferences.model_dump(),
                'behavior':{'intensity':self.preferences.intensity,'quiet':self.gate.quiet,
                            'cooldown':self.gate.cooldown},
                'capabilities':{'seat':True,'clear_data':True,'reported_identity':True,'live_intensity':True},
                'voice_available':{p:bool(os.getenv(env)) and self.cloud.configured('tts') for p,env in VOICE_ENV.items()}}

    def memory_context(self,text=''):
        memory=self.episodes.summaries()+list(self.memory)[-20:]
        item_ids=[]
        if self.build_knowledge and self.build_scope and self.build_scope[:2]==(self.session,self.events.match_id):
            memory.append(self.build_knowledge)
            for build in [self.build_knowledge,*self.build_knowledge.get('alternatives',[])]:
                for section in build['data'].values():
                    for row in (section if isinstance(section,list) else [section]):
                        if isinstance(row,dict):item_ids.extend(row.get('ids',[]))
        if self.long_memory.data['items']:
            memory.append(self.long_memory.context(text,item_ids))
        if self.match_knowledge and self.match_knowledge.match_id==self.events.match_id:
            memory.append(self.match_knowledge.context(text,(self.identity or {}).get('champion')))
        return memory

    def clear_match_research(self):
        if self.build_task and not self.build_task.done():self.build_task.cancel()
        self.build_task=None;self.build_scope=None;self.build_knowledge=None;self.build_retry_at=0
        if self.research_task and not self.research_task.done():
            self.research_task.cancel()
        self.research_task=None;self.research_scope=None;self.match_knowledge=None
        self.state['match_research']='等待本局阵容，临时资料未加载'

    def ensure_match_research(self,data):
        # Public hero/team data only. Never send player IDs, nicknames, voice,
        # credentials or game screenshots to reference websites.
        lineup=[{'champion':p.get('championName'),'team':p.get('team')}
                for p in data.get('allPlayers',[])[:20] if p.get('championName')]
        self.ensure_build_research()
        if not lineup:return
        signature=tuple(sorted((p['champion'],p['team'] or '') for p in lineup))
        scope=(self.session,self.events.match_id,signature)
        if scope==self.research_scope:return
        self.clear_match_research();self.research_scope=scope
        self.state['match_research']='正在联网检索本局阵容、英雄技能与装备外号'
        self.research_task=asyncio.create_task(self.load_match_research(scope,lineup))
        self.ensure_build_research()

    def ensure_build_research(self):
        if not self.gate.running or self.gate.paused:return
        name=(self.identity or {}).get('champion')
        hero=self.long_memory.resolve_champion(name)
        if not hero and self.match_knowledge:
            hero=next((h for h in self.match_knowledge.catalog.values() if name in h['aliases']),None)
        if not hero:
            if self.build_task and not self.build_task.done():self.build_task.cancel()
            self.build_task=None;self.build_scope=None;self.build_knowledge=None
            return
        position='all'
        rows=[p for p in (self.game or {}).get('allPlayers',[]) if p.get('championName')==name]
        if len(rows)==1:
            position={'TOP':'top','MIDDLE':'mid','JUNGLE':'jungle','BOTTOM':'adc','UTILITY':'support'}.get(rows[0].get('position'),'all')
        scope=(self.session,self.events.match_id,hero['key'],position)
        if scope==self.build_scope and (self.build_knowledge or
            (self.build_task and not self.build_task.done()) or time.monotonic()<self.build_retry_at):return
        if self.build_task and not self.build_task.done():self.build_task.cancel()
        self.build_scope=scope;self.build_knowledge=None
        self.state['build_research']='正在提前加载本局英雄出装'
        self.build_task=asyncio.create_task(self.load_champion_build(scope))

    async def load_champion_build(self,scope):
        try:
            build=await asyncio.wait_for(champion_build(scope[2],scope[3]),30)
            if scope!=self.build_scope or not self.gate.running or self.gate.paused:return
            self.build_knowledge=build
            self.state['build_research']=f"出装已预加载：{build['champion']} · {build['position']} · {build['patch'] or '版本未标注'}"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if scope==self.build_scope:
                self.build_retry_at=time.monotonic()+60
                self.state['build_research']='出装源暂不可用；本地装备知识仍可使用'
                self.log('build_research_failed',error=type(exc).__name__)

    async def load_match_research(self,scope,lineup):
        try:
            knowledge=await asyncio.wait_for(research_match(scope[1],lineup),35)
            if scope!=self.research_scope or not self.gate.running or self.gate.paused:return
            self.match_knowledge=knowledge
            self.ensure_build_research()
            self.state['match_research']=(f'本局资料已加载：{len(knowledge.champions)}名英雄、'
                f'{len(knowledge.items)}件装备及外号'+(' · 部分网页未成功读取' if knowledge.errors else ''))
            self.log('match_research_ready',summary=knowledge.summary())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if scope==self.research_scope:
                self.state['match_research']='联网资料暂不可用，本局识别继续运行'
                self.log('match_research_failed',error=type(exc).__name__)

    async def save_preferences(self,prefs):
        if prefs.seat_yaw!=self.preferences.seat_yaw:
            raise ValueError('请使用座位方向的“调整并保存”按钮')
        device_changed=(prefs.input_device,prefs.output_device)!=(self.preferences.input_device,self.preferences.output_device)
        if device_changed and (self.gate.running or self.diagnostic_lock.locked()):
            raise ValueError('请先结束陪玩和本体测试，再切换音频设备')
        if device_changed:
            for direction in ('input','output'):
                selection=getattr(prefs,direction+'_device')
                if selection is not None:
                    choose_device(direction,selection)
        # Persist first: a failed write must not report failure while silently
        # applying the new selection to the running session.
        path=self.root/'preferences.json'
        temporary=path.with_suffix('.tmp')
        temporary.write_text(prefs.model_dump_json(indent=2),encoding='utf8')
        temporary.replace(path)
        intensity_changed=prefs.intensity!=self.preferences.intensity
        await self.halt('更新搭子设置')
        self.preferences=prefs
        self.audio.volume=prefs.volume
        self.audio.input_device=prefs.input_device
        self.audio.output_device=prefs.output_device
        self.role=VOICE_ROLE.get(prefs.voice,self.role)
        self.gate.cooldown={'chill':45,'normal':30,'chaos':8}[prefs.intensity]
        self.gate.relaxed=prefs.intensity=='chaos'
        if intensity_changed:
            self.gate.quiet=False
        return self.preferences_snapshot()

    async def set_intensity(self,intensity):
        # Selecting a mode is an explicit request to use that speaking style,
        # including reselecting the current mode after temporarily going quiet.
        prefs=Preferences(**{**self.preferences.model_dump(),'intensity':intensity})
        await self.save_preferences(prefs)
        self.gate.quiet=False
        return self.preferences_snapshot()

    async def configure_seat(self,yaw):
        if self.gate.running or self.diagnostic_lock.locked() or self.clearing_data:
            raise ValueError('请先结束陪玩和本体测试，再设置座位方向')
        async with self.diagnostic_lock:
            await self.halt('设置座位方向')
            epoch=self.gate.epoch
            result=await asyncio.to_thread(self.robot.face_seat,yaw,lambda:epoch==self.gate.epoch)
            if result.get('cancelled'):
                raise ValueError('座位调整已停止，未保存新方向')
            self.preferences.seat_yaw=float(yaw)
            path=self.root/'preferences.json'
            temporary=path.with_suffix('.tmp')
            temporary.write_text(self.preferences.model_dump_json(indent=2),encoding='utf8')
            temporary.replace(path)
            return {**result,**self.preferences_snapshot()}

    async def clear_local_data(self):
        if self.diagnostic_lock.locked() or self.clearing_data:
            raise ValueError('请先结束本体测试，再清除记录')
        self.clearing_data=True
        try:
            jobs=list(self.active_jobs)
            owners=list(self.owner_tasks)
            await self.control('end')
            if self.mic_thread and self.mic_thread.is_alive():
                raise ValueError('麦克风尚未完全停止，未清除持久记录；请稍后重试')
            for owner in owners:
                if owner is not asyncio.current_task() and not owner.done():
                    owner.cancel()
                    jobs.append(owner)
            if jobs:
                await asyncio.gather(*jobs,return_exceptions=True)
            self.usage_clear_before=time.monotonic()
            self.usages.clear()
            self.logs.clear()
            directory=(self.root/'evidence').resolve()
            deleted=[]
            for name in ('usage.jsonl','decisions.jsonl','decisions.previous.jsonl','hardware.jsonl'):
                path=directory/name
                if path.resolve().parent!=directory:
                    raise ValueError('诊断路径超出本地记录目录，已停止清除')
                if path.exists():
                    path.unlink()
                    deleted.append(name)
            self.state['microphone']='会话与收音记录已清除 · 当前未收听'
            self.state['speaker']='播放记录已清除'
            self.state['motion']='动作记录已清除'
            return {'cleared':True,'deleted_files':deleted,'settings_retained':True,
                    'scope':'当前会话缓存与应用运行日志；独立验收文件和云端留存不在此范围'}
        finally:
            self.clearing_data=False

    def relevant_events(self,events):
        prefs=self.preferences.normalized_events()
        result=[]
        for event in events:
            kind=EVENT_TYPES.get(event.get('EventName'))
            if kind=='kill' and self.identity and event.get('VictimName') in self.identity.get('aliases',[self.identity.get('name')]):
                kind='death'
            if kind and (not prefs[kind].enabled or prefs[kind].reaction=='Silent'):
                continue
            result.append(event)
        return result

    def kill_reaction_allowed(self, now, starting=True, detected_at=None):
        """Very short verified kill cheers can play outside base/idle scenes.

        Unlike long commentary, a requested brief celebration does not require
        combat to stop. Foreground game, fresh API, connection and controls apply.
        """
        checks=[(self.gate.running and not self.gate.paused,'采集未开启'),
                (not self.gate.quiet,'已安静'),
                (self.gate.robot_ready and now-self.gate.robot_at<5,'本体未就绪'),
                (not starting or not self.gate.owner_speaking or
                 (detected_at is not None and now-detected_at>=4),'正在收听，稍后庆祝'),
                (self.gate.game_present is True and 0<=now-self.game_at<1.5,'对局接口过期'),
                (self.capture_valid and bool(self.buffer.frames) and
                 0<=now-self.buffer.frames[-1].at<1.2,'等待游戏回到前台'),
                (not starting or now-self.gate.last_spoken>=4,'短回应间隔')]
        for ok,reason in checks:
            if not ok:
                self.state['event_reaction']=reason
                return False
        self.state['event_reaction']='已确认击杀，可以短回应'
        return True

    def output_allowed(self, now):
        if self.speech_candidate and not self.speech_candidate.proactive:
            return self.dialogue_allowed(now)
        if self.speech_candidate and self.speech_candidate.purpose=='kill_reaction':
            return self.kill_reaction_allowed(now,False)
        if self.speech_candidate and self.speech_candidate.purpose=='death_reaction':
            return self.death_reaction_allowed(now,False)
        return self.gate.allowed(now,False)

    def update_owner_life(self,data,now):
        self.gate.owner_dead=False
        self.gate.owner_dead_at=now
        if not self.identity or self.identity.get('source')=='owner_reported':
            return
        names=set(self.identity.get('aliases',[]))
        players=[p for p in data.get('allPlayers',[]) if names.intersection(aliases(p))]
        self.gate.owner_dead=len(players)==1 and boolean(players[0].get('isDead')) is True

    def death_reaction_allowed(self,now,starting=True,detected_at=None):
        allowed=self.gate.respawning(now) and self.kill_reaction_allowed(now,starting,detected_at)
        if allowed:
            self.state['event_reaction']='已确认阵亡，可以短鼓励'
        return allowed

    def queue_death_reactions(self,events):
        if (not self.gate.running or self.gate.paused or self.gate.quiet
                or not self.identity or self.identity.get('source')=='owner_reported'):
            return
        names=set(self.identity.get('aliases',[]))
        lines=('这波打得憋屈，缓口气，复活咱们再来。',
               '别让这一波影响心情，等复活我们再打回来。',
               '先歇口气，这波过去了，下一波我陪你。',
               '趁复活这会儿放松一下，手别绷太紧。',
               '陪你等复活，不急着跟这一波较劲。',
               '缓一缓，咱们还有下一次机会。',
               '喝口水歇一下，复活了再接着打。')
        for event in self.relevant_events(events):
            if (event.get('EventName')!='ChampionKill' or event.get('VictimName') not in names
                    or event['event_key'] in self.reacted_events):
                continue
            recent=self.conversation.snapshot()['recent_replies']
            text=next((line for line in lines if line not in recent),lines[len(self.reacted_events)%len(lines)])
            self.pending.appendleft(Candidate(text,self.role,self.gate.epoch,time.monotonic(),
                [event['event_key']],True,'neutral',purpose='death_reaction'))
            self.reacted_events.append(event['event_key'])
            self.state['last_game_event']='检测到你阵亡，准备短鼓励'
            self.log('event_candidate',purpose='owner_death',evidence=[event['event_key']])

    def dialogue_allowed(self,now):
        # The owner explicitly addressed the assistant. Their requested answer
        # is not unsolicited commentary and must not wait for visual idle.
        return (self.gate.running and not self.gate.paused and self.gate.robot_ready
                and 0<=now-self.gate.robot_at<5)

    async def halt_game_commentary(self,reason):
        # Losing/changing a game frame invalidates commentary, not a direct
        # conversation. Explicit stop/pause/end still use halt() for everything.
        self.pending=deque((c for c in self.pending if not c.proactive),maxlen=3)
        self.facts_revision+=1
        if self.audio.playing and (self.speech_candidate is None or self.speech_candidate.proactive):
            await self.halt(reason,invalidate=False)
        self.log('cancel',reason=reason,purpose='game_commentary_only')

    def queue_kill_reactions(self, events):
        if not self.identity or self.identity.get('source')=='owner_reported':
            return
        names=set(self.identity.get('aliases',[]))
        for event in self.relevant_events(events):
            if event.get('EventName') not in ('ChampionKill','Multikill') or event.get('KillerName') not in names:
                continue
            self.state['last_game_event']='检测到你的连杀' if event['EventName']=='Multikill' else '检测到你的击杀'
            self.log('game_event',purpose='owner_kill',evidence=[event['event_key']])
            if self.event_reactions.full():
                self.event_reactions.get_nowait()
            self.event_reactions.put_nowait((self.session,self.gate.epoch,time.monotonic(),event))

    async def event_reaction_loop(self):
        while True:
            first=await self.event_reactions.get()
            await asyncio.sleep(.45)  # Merge a kill and its same-poll multikill.
            rows=[first]
            while not self.event_reactions.empty():
                rows.append(self.event_reactions.get_nowait())
            now=time.monotonic()
            rows=[row for row in rows if row[0]==self.session and row[1]==self.gate.epoch and now-row[2]<8]
            if not rows or not self.gate.running or self.gate.paused or self.gate.quiet:
                continue
            epoch=self.gate.epoch;session=self.session
            events=[row[3] for row in rows]
            try:
                with request_scope(session_id=session,phase='kill_reaction'):
                    reply=await self.job(self.cloud.event_reply(self.role,events,
                        self.conversation.snapshot()['recent_replies'],self.preferences.model_dump()))
                if not reply:
                    self.state['event_reaction']='击杀已识别，但模型未提供可播放的回应'
                    self.log('event_failed',reason='no_valid_reply')
                    continue
                if (epoch!=self.gate.epoch or session!=self.session or not self.gate.running
                        or self.gate.paused or self.gate.quiet or time.monotonic()-rows[0][2]>15):
                    continue
                self.pending.appendleft(Candidate(reply.text,self.role,epoch,rows[0][2],reply.evidence,
                                                 True,reply.motion,purpose='kill_reaction'))
                self.reacted_events.extend(e['event_key'] for e in events)
                self.state['event_reaction']='击杀回应已生成，等待短暂空隙'
                self.log('event_candidate',purpose='owner_kill',evidence=reply.evidence,source_at=rows[0][2])
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception as exc:
                self.state['event_reaction']='击杀已识别，但回应生成失败：'+type(exc).__name__
                self.log('event_failed',error=type(exc).__name__)

    async def audition(self,profile):
        if self.clearing_data:
            raise ValueError('正在清除本地数据，请稍候')
        if profile not in VOICE_ENV:
            raise ValueError('未知声线')
        if self.gate.running:
            raise ValueError('请先结束陪玩，再试听声线')
        if self.diagnostic_lock.locked():
            raise ValueError('另一项本体测试正在进行')
        if not self.preferences_snapshot()['voice_available'][profile]:
            raise ValueError('这条声线尚未配置。请在本地 .env 配置 '+VOICE_ENV[profile]+' 与 TTS 模型后重载。')
        async with self.diagnostic_lock:
            epoch=self.gate.epoch
            wav=await self.cloud.tts('哈喽，今天也陪你一起玩。',VOICE_ROLE[profile],profile)
            return await asyncio.to_thread(self.audio.play,wav,lambda:epoch==self.gate.epoch)

    async def boot(self):
        self.loop = asyncio.get_running_loop()
        self.tasks = [asyncio.create_task(fn()) for fn in
                      (self.robot_status_loop,self.game_presence_loop,self.game_loop,self.capture_loop,self.safety_loop,self.analysis_loop,self.event_reaction_loop,self.speech_loop,self.preload_knowledge,self.preload_expressions)]

    async def preload_knowledge(self):
        try:
            await self.long_memory.refresh()
            self.state['equipment_memory']=f"本地长期装备知识：{len(self.long_memory.data['items'])}件"
            self.ensure_build_research()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.long_memory.error=type(exc).__name__
            self.state['equipment_memory']='使用本地装备缓存；联网更新暂不可用'

    async def preload_expressions(self):
        try:
            await self.robot.expressions.preload()
            count=len(self.robot.expressions.summary()['loaded'])
            self.state['expression_skills']=f'HF社区动作已加载：{count} / 34'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state['expression_skills']='HF动作加载失败：'+type(exc).__name__

    async def shutdown(self):
        await self.control('end')
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.cloud.client.aclose()
        await asyncio.to_thread(self.robot.close)

    async def robot_status_loop(self):
        async with httpx.AsyncClient(timeout=1,trust_env=False) as client:
            while True:
                was_ready=self.gate.robot_ready
                try:
                    response=await client.get('http://127.0.0.1:8000/api/daemon/status')
                    response.raise_for_status()
                    status=response.json()
                    telemetry=None
                    if needs_live_probe(status):
                        response=await client.get('http://127.0.0.1:8000/api/state/full?with_head_joints=true')
                        response.raise_for_status()
                        telemetry=response.json()
                    ready,reason=robot_health(status,telemetry)
                    self.gate.robot_ready=ready
                    self.gate.robot_at=time.monotonic()
                    self.state['robot']=reason if ready else '机器人未就绪：'+reason
                    if not self.gate.robot_ready and self.gate.running and (was_ready or self.audio.playing):
                        await self.halt('机器人状态异常')
                    if was_ready and not self.gate.robot_ready:
                        await asyncio.to_thread(self.robot.close)
                except Exception as exc:
                    self.gate.robot_ready=False
                    self.state['robot']='未连接：'+type(exc).__name__
                    if self.gate.running and (was_ready or self.audio.playing):
                        await self.halt('机器人断开')
                    if was_ready:
                        await asyncio.to_thread(self.robot.close)
                await asyncio.sleep(2)

    async def halt(self, reason, invalidate=True):
        if invalidate:
            if reason!='主人新话轮':
                self.facts_revision+=1
            self.gate.invalidate(reason)
            self.pending.clear()
        self.robot.stop()
        await asyncio.to_thread(self.audio.stop)
        self.log('cancel',reason=reason)

    async def control(self, action, value=None):
        if self.clearing_data and action not in ('end','stop'):
            raise ValueError('正在清除本地数据，请稍候')
        if action == 'connect':
            if self.gate.running:
                raise ValueError('请先结束陪玩，再重新连接本体')
            async with httpx.AsyncClient(timeout=8,trust_env=False) as client:
                response=await client.get('http://127.0.0.1:8000/api/daemon/status')
                response.raise_for_status()
                status=response.json()
                if status.get('state')!='running' or status.get('error') or status.get('simulation_enabled') or status.get('mockup_sim_enabled'):
                    raise ValueError('真实机器人服务尚未运行：'+str(status.get('error') or status.get('state')))
                if not status.get('no_media') and not status.get('media_released'):
                    lock=await client.get('http://127.0.0.1:8000/api/daemon/robot-app-lock-status')
                    lock.raise_for_status()
                    if lock.json().get('state')!='free':
                        raise ValueError('其他官方应用正在使用本体，请先在 Reachy Mini Control 中结束该应用')
                    released=await client.post('http://127.0.0.1:8000/api/media/release')
                    released.raise_for_status()
                    response=await client.get('http://127.0.0.1:8000/api/daemon/status')
                    response.raise_for_status()
                    status=response.json()
                telemetry=None
                if needs_live_probe(status):
                    response=await client.get('http://127.0.0.1:8000/api/state/full?with_head_joints=true')
                    response.raise_for_status()
                    telemetry=response.json()
                ready,reason=robot_health(status,telemetry)
                self.gate.robot_ready=ready
                self.gate.robot_at=time.monotonic()
                self.state['robot']=reason if ready else '机器人未就绪：'+reason
                if not ready:
                    raise ValueError(reason)
        elif action == 'start':
            if self.clearing_data:
                raise ValueError('正在清除本地数据，请稍候')
            if self.diagnostic_lock.locked():
                raise ValueError('请等待本体诊断结束')
            if self.gate.running:
                raise ValueError('会话已开始，请使用恢复采集')
            if not self.gate.robot_ready or time.monotonic()-self.gate.robot_at>=5:
                raise ValueError('Reachy 本体尚未就绪：'+self.state['robot'])
            if self.preferences.seat_yaw is not None:
                async with self.diagnostic_lock:
                    epoch=self.gate.epoch
                    result=await asyncio.to_thread(self.robot.face_seat,self.preferences.seat_yaw,
                                                  lambda:epoch==self.gate.epoch)
                    if result.get('cancelled'):
                        raise ValueError('座位方向恢复已中断，陪玩尚未开始')
            self.gate.running, self.gate.paused = True, False
            self.gate.game_present=None
            self.gate.game_presence_at=-1000
            self.identity_questions=0
            self.identity_question_at=-1000
            self.ready_announced=False
            self.session = str(uuid.uuid4())
            self.conversation.clear()
            self.clear_match_research()
            self.reacted_events.clear()
            self.gate.invalidate('开始观察')
            self.log('session_started',cloud_notice='选定游戏窗口与主人语音按需提交给配置的模型供应商')
            self.state['dialogue']='正在听你说'
            if self.cloud.configured('asr'):
                self.start_mic()
        elif action in ('pause','end'):
            self.gate.paused = True
            self.gate.game_present=None
            self.gate.game_presence_at=-1000
            self.mic_stop.set()
            self.state['microphone']='已停止收听'
            self.state['dialogue']='已停止收听'
            await self.halt('暂停采集' if action=='pause' else '结束会话')
            for job in list(self.active_jobs):
                job.cancel()
            while not self.analysis.empty():
                self.analysis.get_nowait()
            while not self.safety_analysis.empty():
                self.safety_analysis.get_nowait()
            self.buffer.clear()
            self.episodes.detach()
            self.capture_valid=False
            self.capture_segment+=1
            self.clear_reported_identity()
            self.capture.previous=None
            self.visual_safety.clear()
            self.recent_events.clear()
            if self.mic_thread:
                await asyncio.to_thread(self.mic_thread.join,2)
            self.audio.reference.clear()
            self.conversation.clear()
            self.clear_match_research()
            while not self.event_reactions.empty():
                self.event_reactions.get_nowait()
            if action == 'end':
                self.gate.running = False
                self.memory.clear()
                self.logs.clear()
                self.latest = self.identity = self.game = None
                self.identities = Identity()
                self.episodes.clear()
                self.events = Events()
                self.session = None
                self.state.pop('last_heard',None)
                self.state.pop('last_reply',None)
        elif action == 'resume':
            if not self.gate.running:
                raise ValueError('会话未开始')
            self.gate.paused = False
            self.gate.game_present=None
            self.gate.game_presence_at=-1000
            self.gate.invalidate('恢复观察')
            if self.cloud.configured('asr'):
                self.start_mic()
        elif action == 'quiet':
            self.gate.quiet = True
            await self.halt('安静')
        elif action == 'unquiet':
            self.gate.quiet = False
        elif action == 'role':
            if value not in ('aqi','anao'):
                raise ValueError('未知角色')
            await self.halt('切换角色')
            self.role = value
            if self.preferences.voice:
                alternate={'velvet':'sparkle','sparkle':'velvet','cedar':'breeze','breeze':'cedar'}
                if VOICE_ROLE[self.preferences.voice]!=value:
                    self.preferences.voice=alternate[self.preferences.voice]
        elif action == 'window':
            await self.halt('切换窗口')
            self.capture.select(int(value))
            self.buffer.clear()
            self.episodes.detach()
            self.capture_segment+=1
            self.clear_reported_identity()
            self.capture_valid=False
            self.visual_safety.clear()
            self.state['capture'] = '窗口已选择，待前台采集'
        elif action == 'stop':
            await self.halt('手动停止输出')
        elif action == 'volume':
            level=float(value)
            if not math.isfinite(level):
                raise ValueError('音量必须是有限数值')
            self.audio.volume = max(0,min(1,level))
        else:
            raise ValueError('未知操作')

    async def job(self, coro):
        task = asyncio.create_task(coro)
        self.active_jobs.add(task)
        try:
            return await task
        finally:
            self.active_jobs.discard(task)

    async def update_game_presence(self, present, observed_at):
        previous=self.gate.game_present
        self.gate.game_present=present
        self.gate.game_presence_at=observed_at
        if previous is not None and previous!=present:
            await self.halt('对局启动，重新检查发言时机' if present is not False else '对局已结束')
        if present is True and previous is not True:
            self.state['vision_safety']='已进入对局，检查当前发言时机'
        if present is False:
            self.state['capture']='未在对局中 · 可以直接聊天'
            self.state['vision_safety']='未开局 · 仅回应你的话'
            if previous is not False:
                self.clear_match_research()
                self.state.pop('last_game_event',None)
                self.state.pop('event_reaction',None)
                self.capture_valid=False
                self.capture_segment+=1
                self.capture.hwnd=None
                self.capture.previous=None
                self.buffer.clear()
                self.visual_safety.clear()
                self.gate.visual_safe=False
                self.episodes.detach()
                self.clear_reported_identity()
                self.latest=self.identity=None
                self.recent_events=[]

    async def game_presence_loop(self):
        while True:
            if self.gate.running and not self.gate.paused:
                session=self.session
                try:
                    process_present=await asyncio.to_thread(game_process_running)
                    present=process_present or bool(self.game and time.monotonic()-self.game_at<1.5)
                except Exception:
                    present=None
                if self.gate.running and not self.gate.paused and session==self.session:
                    await self.update_game_presence(present,time.monotonic())
                    if present:
                        games=[w for w in windows() if w.get('is_game')]
                        if len(games)==1 and self.capture.hwnd!=games[0]['hwnd']:
                            try:
                                await self.control('window',games[0]['hwnd'])
                            except (ValueError,RuntimeError):
                                self.state['capture']='等待有效的游戏窗口'
            await asyncio.sleep(.5)

    async def game_loop(self):
        async with httpx.AsyncClient(verify=False,trust_env=False,timeout=1.2) as client:
            while True:
                if self.gate.running and not self.gate.paused:
                    request_epoch=self.gate.epoch
                    request_session=self.session
                    try:
                        r = await client.get('https://127.0.0.1:2999/liveclientdata/allgamedata')
                        r.raise_for_status()
                        data = r.json()
                        if request_epoch!=self.gate.epoch or not self.gate.running or self.gate.paused:
                            continue
                        if self.gate.game_present is not True:
                            await self.update_game_presence(True,time.monotonic())
                        fresh, new_match = self.events.ingest(data)
                        if new_match:
                            self.clear_match_research()
                            self.state.pop('last_game_event',None)
                            self.state.pop('event_reaction',None)
                            await self.halt('新对局')
                            self.visual_safety.clear()
                            self.buffer.clear()
                            self.episodes.detach()
                            self.identity = None
                            self.health = None
                            self.latest = None
                            self.recent_events = []
                            self.last_episode_at = -1000
                        if self.identities.reported_owner:
                            await self.halt('接口恢复，重新核实身份')
                            self.clear_reported_identity()
                            self.episodes.revoke_match(self.events.match_id)
                            self.latest=None
                        if not self.gate.running or self.gate.paused or self.session!=request_session:
                            continue
                        self.game, self.game_at = data, time.monotonic()
                        self.identity = self.identities.update(data,self.events.match_id)
                        self.update_owner_life(data,self.game_at)
                        self.ensure_match_research(data)
                        self.queue_kill_reactions(fresh)
                        self.queue_death_reactions(fresh)
                        self.recent_events = (self.recent_events+self.relevant_events(fresh))[-30:]
                        self.state['game_api'] = '真实 Live Client Data 已连接'
                    except Exception as exc:
                        self.events.connected = False
                        self.game = None
                        self.gate.owner_dead=False
                        self.identities.disconnect()
                        self.identity=self.identities.context()
                        self.state['game_api'] = ('未开局，等待对局' if self.gate.game_present is False
                                                  else f'未连接：{type(exc).__name__}')
                await asyncio.sleep(.5)

    def clear_reported_identity(self):
        self.identities.clear_report()
        if self.identity and self.identity.get('source')=='owner_reported':
            self.identity=None
        self.memory=deque((m for m in self.memory if
                           (m.get('identity') or {}).get('source')!='owner_reported'),maxlen=30)

    async def report_identity(self,report):
        if (not self.gate.running or self.gate.paused or not self.capture_valid
                or not self.buffer.frames or time.monotonic()-self.buffer.frames[-1].at>1.2):
            raise ValueError('请先开始陪玩并保持实际游戏窗口在前台，再确认本局身份')
        scope=f'visual:{self.session}:{self.capture.hwnd}:{self.capture_segment}'
        identity=self.identities.report(report,scope)
        expected_epoch=self.gate.epoch+1
        await self.halt('主人自报本局身份')
        if (self.gate.epoch!=expected_epoch or not self.gate.running or self.gate.paused
                or self.identities.context()!=identity):
            raise ValueError('游戏或会话状态已变化，请重新确认身份')
        self.identity=identity
        self.ensure_build_research()
        self.latest=None
        self.episodes.revoke_match(self.events.match_id)
        self.recent_events=[]
        self.memory=deque((m for m in self.memory if m.get('match_id')!=self.events.match_id
                           or m['kind'] not in ('observed_fact','inference')),maxlen=30)
        self.memory.append({'kind':'owner_statement','match_id':self.events.match_id,
                            'text':'本局身份由主人自报，未通过接口核实','identity':identity})
        self.pending.append(Candidate('记住啦，这局就陪你玩这个英雄。',self.role,
                                      self.gate.epoch,time.monotonic(),[],False,'neutral',
                                      purpose='identity_confirmation'))
        return self.identities.snapshot()

    def queue_identity_question(self,source_at):
        now=time.monotonic()
        if (self.identity or self.identity_questions>=2 or now-self.identity_question_at<90
                or self.pending or not self.gate.running or self.gate.paused or self.gate.quiet):
            return False
        self.pending.append(Candidate('这局你玩什么英雄？有一起排的朋友吗？',self.role,self.gate.epoch,
                                      source_at,[],True,'neutral',purpose='identity_question'))
        self.identity_questions+=1
        self.identity_question_at=now
        return True

    async def confirm_identity(self, match_id, name, friends):
        identity=self.identities.confirm(match_id,name,friends)
        await self.halt('主人纠正身份或朋友')
        self.identity=identity
        self.ensure_build_research()
        self.latest=None
        self.episodes.revoke_match(match_id)
        self.recent_events=[]
        self.memory=deque((m for m in self.memory if m.get('match_id')!=match_id
                           or m['kind'] not in ('observed_fact','inference')),maxlen=30)
        self.memory.append({'kind':'correction','match_id':match_id,
                            'text':'本局身份与朋友以主人最新确认为准','identity':identity})
        return self.identities.snapshot()

    async def probe_identity(self):
        if self.gate.running and not self.gate.paused:
            return self.identities.snapshot()
        epoch=self.gate.epoch
        async with httpx.AsyncClient(verify=False,trust_env=False,timeout=3) as client:
            response=await client.get('https://127.0.0.1:2999/liveclientdata/allgamedata')
            response.raise_for_status()
            data=response.json()
        if epoch!=self.gate.epoch:
            raise ValueError('会话已变化，请重新读取身份')
        _,new_match=self.events.ingest(data)
        if new_match:
            await self.halt('新对局')
            self.visual_safety.clear()
            self.buffer.clear()
            self.episodes.detach()
            self.latest=None
            self.health=None
            self.recent_events=[]
            self.last_episode_at=-1000
        self.identity=self.identities.update(data,self.events.match_id)
        self.state['game_api']='真实 Live Client Data 已连接'
        return self.identities.snapshot()

    async def capture_loop(self):
        last_submit = -1000
        last_safety_submit = -1000
        while True:
            cycle_started=time.monotonic()
            if self.gate.game_present is False and 0<=cycle_started-self.gate.game_presence_at<1.5:
                await asyncio.sleep(.5)
                continue
            if self.gate.running and not self.gate.paused:
                capture_scope=(self.session,self.capture.hwnd,self.capture_segment,self.events.match_id)
                try:
                    jpeg = await asyncio.to_thread(self.capture.grab)
                    now = time.monotonic()
                    if (capture_scope!=(self.session,self.capture.hwnd,self.capture_segment,self.events.match_id)
                            or not self.gate.running or self.gate.paused):
                        continue
                    game_time = self.game.get('gameData',{}).get('gameTime') if self.game else None
                    frame=Frame(str(uuid.uuid4()),now,jpeg,game_time,self.capture.hwnd,
                                self.capture_segment,self.capture.width,self.capture.height)
                    self.buffer.add(frame)
                    self.capture_valid=True
                    self.state['capture'] = '真实游戏窗口采集中 · 2 Hz'
                    stats = (self.game or {}).get('activePlayer',{}).get('championStats',{})
                    hp, maximum = stats.get('currentHealth'), stats.get('maxHealth')
                    has_health=(all(isinstance(v,(int,float)) and not isinstance(v,bool)
                                    and math.isfinite(v) for v in (hp,maximum)) and maximum>0
                                and now-self.game_at<1.5)
                    local_safe = (has_health and hp/maximum>.35 and self.health is not None
                                  and hp>=self.health-1 and self.capture.change<.055
                                  and now-self.game_at<1.5)
                    visual_continuous=self.visual_safety.observe(frame)
                    if has_health and not local_safe:
                        self.visual_safety.clear()
                        visual_continuous=False
                    self.gate.visual_continuity_at=self.visual_safety.verified_at if visual_continuous else -1000
                    if not has_health:
                        local_safe=visual_continuous
                        self.state['capture']='真实游戏窗口采集中 · 2 Hz · 画面降级判断（待实局验证）'
                    self.health = hp
                    self.gate.observe(now,local_safe)
                    if self.audio.playing and not self.output_allowed(now):
                        await self.halt('本地风险或画面状态失效')
                    if self.cloud.configured('vision') and now-last_safety_submit>=3 and len(self.buffer.frames)>=2:
                        if self.safety_analysis.full():
                            self.safety_analysis.get_nowait()
                        self.safety_analysis.put_nowait((self.session,self.capture_segment))
                        last_safety_submit=now
                    if self.cloud.configured('vision') and (self.recent_events or now-last_submit>=4):
                        frames = self.buffer.sample(now,seconds=4 if self.game is None else 8)
                        if len(frames)>=2:
                            events=list(self.recent_events)
                            if self.analysis.full():
                                _,old_frames,old_events,_=self.analysis.get_nowait()
                                if old_frames and (old_frames[-1].window_id,old_frames[-1].segment)==(frame.window_id,frame.segment):
                                    events=list({e['event_key']:e for e in old_events+events
                                                 if e.get('match_id')==self.events.match_id}.values())[-30:]
                                old_frames.clear()
                            item = (self.gate.epoch,frames,events,self.identity)
                            self.analysis.put_nowait(item)
                            self.recent_events = []
                            last_submit = now
                except Exception as exc:
                    self.state['capture'] = str(exc)
                    self.gate.observe(time.monotonic(),False)
                    self.gate.visual_safe = False
                    self.capture.previous=None
                    self.visual_safety.clear()
                    self.buffer.clear()
                    self.episodes.detach()
                    if self.capture_valid or self.audio.playing:
                        self.capture_segment+=1
                        self.clear_reported_identity()
                        await self.halt_game_commentary('游戏画面不可用')
                    self.capture_valid=False
                finally:
                    jpeg=None
            await asyncio.sleep(max(.01,.5-(time.monotonic()-cycle_started)))

    async def safety_loop(self):
        """Short current-scene checks continue while the owner is talking."""
        while True:
            session,segment=await self.safety_analysis.get()
            if (not self.gate.running or self.gate.paused or not self.capture_valid
                    or session!=self.session or segment!=self.capture_segment):
                continue
            frames=list(self.buffer.frames)[-2:]
            if len(frames)<2 or time.monotonic()-frames[-1].at>1.2:
                continue
            hwnd=self.capture.hwnd
            match_id=self.events.match_id
            try:
                with request_scope(session_id=session,phase='current_scene_safety'):
                    result=await self.job(self.cloud.safety(frames))
                if (not self.gate.running or self.gate.paused or session!=self.session
                        or segment!=self.capture_segment or hwnd!=self.capture.hwnd
                        or match_id!=self.events.match_id or not self.capture_valid):
                    continue
                if frames[-1].at<self.gate.visual_at:
                    continue
                self.gate.visual_at=frames[-1].at
                self.gate.visual_safe=result.safe
                anchored=self.visual_safety.accept(result,frames)
                continuous=anchored and self.visual_safety.revalidate(self.buffer.frames,time.monotonic())
                self.gate.visual_continuity_at=self.visual_safety.verified_at if continuous else -1000
                self.state['vision_safety']=('安全画面已核实' if continuous else
                    result.outcome if not result.safe and result.outcome else '画面已变化或安全结果过期，等待重新核实')
                self.log('safety_check',safe=result.safe,continuous=bool(continuous),
                         reason=self.visual_safety.reason,
                         source_age_ms=round((time.monotonic()-frames[-1].at)*1000))
                if (not result.safe and not self.gate.relaxed and not self.gate.respawning(time.monotonic())
                        and self.audio.playing and self.speech_candidate
                        and self.speech_candidate.proactive and self.speech_candidate.purpose not in ('kill_reaction','death_reaction')):
                    await self.halt_game_commentary('当前画面有风险')
                if (self.gate.allowed(time.monotonic()) and not self.ready_announced and not self.pending
                        and self.identities.snapshot().get('fresh') and self.identity):
                    champion=self.identity.get('champion')
                    if champion:
                        self.pending.append(Candidate(f'这局识别到你玩的是{champion}。',
                            self.role,self.gate.epoch,time.monotonic(),[],True,'nod',purpose='session_ready'))
                        self.ready_announced=True
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling() or not self.gate.paused:
                    raise
            except Exception as exc:
                self.state['vision_safety']='安全画面检查失败：'+type(exc).__name__
                self.log('safety_failed',error=type(exc).__name__)
            finally:
                frames.clear()

    async def analysis_loop(self):
        while True:
            epoch,frames,events,identity = await self.analysis.get()
            if (not self.gate.running or self.gate.paused or not frames
                    or frames[-1].window_id!=self.capture.hwnd or frames[-1].segment!=self.capture_segment):
                frames.clear()
                continue
            scope=(self.session,self.capture.hwnd,self.capture_segment,self.events.match_id,self.facts_revision)
            try:
                self.state['cloud'] = '分析真实画面'
                owner_context=[m for m in self.memory if m.get('match_id')==self.events.match_id
                               and m['kind'] in ('correction','owner_statement')][-6:]
                evidence_frames,previous_episode=self.episodes.prepare(self.events.match_id,frames)
                analysis_id=uuid.uuid4().hex
                with request_scope(session_id=self.session,analysis_id=analysis_id,phase='vision_analysis'):
                    result = await self.job(self.cloud.analyze(evidence_frames,events,identity,owner_context,previous_episode))
                if (not self.gate.running or self.gate.paused or
                        scope!=(self.session,self.capture.hwnd,self.capture_segment,self.events.match_id,self.facts_revision)):
                    continue
                # Timestamp remains the source capture time, never request completion.
                if frames[-1].at>=self.gate.visual_at:
                    self.gate.visual_at = frames[-1].at
                    self.gate.visual_safe = result.safe
                    anchored=self.visual_safety.accept(result,frames)
                    continuous=anchored and self.visual_safety.revalidate(self.buffer.frames,time.monotonic())
                    self.gate.visual_continuity_at=self.visual_safety.verified_at if continuous else -1000
                self.latest = result.model_dump()
                episode=self.episodes.record(self.events.match_id,frames,evidence_frames,events,self.latest)
                if episode:
                    self.latest.update(episode_id=episode.id,match_id=episode.match_id)
                self.log('episode_decision',episode_id=episode.id if episode else None,
                         revision=episode.revision if episode else None,analysis_id=analysis_id,
                         previous_episode_id=(previous_episode or {}).get('episode_id'),
                         merged=bool(episode and episode.id==(previous_episode or {}).get('episode_id')),
                         evidence=[f.id for f in evidence_frames],source_at=frames[-1].at,
                         summary=decision_summary(self.latest,identity))
                self.state['cloud'] = '画面分析返回，待本地门控'
                if (not result.safe and not self.gate.relaxed and not self.gate.respawning(time.monotonic())
                        and frames[-1].at>=self.gate.visual_at and self.audio.playing
                        and (self.speech_candidate is None or
                             (self.speech_candidate.proactive and self.speech_candidate.purpose not in ('kill_reaction','death_reaction')))):
                    await self.halt_game_commentary('视觉风险')
                # Speech changes the reply turn, not the source game observations.
                if epoch!=self.gate.epoch:
                    continue
                if result.safe and not result.meaningful and self.queue_identity_question(frames[-1].at):
                    continue
                already_reacted=any(e['event_key'] in self.reacted_events for e in events)
                if result.meaningful and episode and not episode.spoken and not already_reacted and time.monotonic()-frames[-1].at<20:
                    with request_scope(session_id=self.session,analysis_id=analysis_id,episode_id=episode.id,phase='proactive_reply'):
                        reply = await self.job(self.cloud.reply(self.role,self.latest,self.memory_context(),preferences=self.preferences.model_dump()))
                    if reply.text and epoch==self.gate.epoch:
                        self.pending=deque((c for c in self.pending if c.episode_id!=episode.id),maxlen=3)
                        self.pending.append(Candidate(reply.text,self.role,epoch,frames[-1].at,
                                                      reply.evidence,True,reply.motion,episode.id,episode.revision,
                                                      analysis_id=analysis_id))
                        self.log('episode_candidate',episode_id=episode.id,revision=episode.revision,analysis_id=analysis_id,
                                 evidence=reply.evidence,source_at=frames[-1].at,expires_at=frames[-1].at+20)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling() or not self.gate.paused:
                    raise
            except Exception as exc:
                self.state['cloud'] = f'失败：{type(exc).__name__}: {exc}'
                if (scope==(self.session,self.capture.hwnd,self.capture_segment,self.events.match_id,self.facts_revision)
                        and frames[-1].at>=self.gate.visual_at):
                    self.gate.visual_safe = False
                self.log('analysis_failed',error=type(exc).__name__)
            finally:
                frames.clear()
                evidence_frames=None

    async def speech_loop(self):
        while True:
            if self.pending:
                # A waiting game comment must not block a requested answer.
                direct=next((c for c in self.pending if not c.proactive),None)
                priority=direct or next((c for c in self.pending if c.purpose in ('kill_reaction','death_reaction')),None)
                if priority is not None and self.pending[0] is not priority:
                    self.pending.remove(priority);self.pending.appendleft(priority)
                item = self.pending[0]
                now = time.monotonic()
                if not item.valid(self.gate,self.role,now) or (item.episode_id and
                        not self.episodes.valid(item.episode_id,item.episode_revision)):
                    self.pending.popleft()
                    self.log('expired_candidate',episode_id=item.episode_id)
                elif (self.dialogue_allowed(now) if not item.proactive else
                      self.kill_reaction_allowed(now,detected_at=item.created) if item.purpose=='kill_reaction' else
                      self.death_reaction_allowed(now,detected_at=item.created) if item.purpose=='death_reaction' else self.gate.allowed(now,True)):
                    self.pending.popleft()
                    problem=reply_problem(item.text,self.conversation.completed_replies())
                    # Intentional repetitions of a direct answer are handled at
                    # generation time; proactive comments must not repeat either.
                    if problem and item.purpose!='name_call' and (item.proactive or problem in ('empty_reassurance','stock_opener')):
                        self.log('reply_rejected',reason=problem,turn_id=item.turn_id)
                        continue
                    playback_session=self.session
                    played_row=None
                    self.speech_candidate=item
                    try:
                        with request_scope(session_id=self.session,analysis_id=item.analysis_id,episode_id=item.episode_id,
                                           turn_id=item.turn_id,phase='speech_synthesis',input_finished_at=item.input_finished_at):
                            self.state['dialogue']='正在准备声音'
                            wav = await self.job(self.cloud.tts(item.text,item.role,self.preferences.voice))
                        started=[False]
                        valid = lambda: (item.valid(self.gate,self.role,time.monotonic())
                            and self.output_allowed(time.monotonic())
                            and (not item.episode_id or self.episodes.valid(item.episode_id,item.episode_revision,started[0])))
                        if valid():
                            def on_first():
                                nonlocal played_row
                                played_row=self.conversation.playback(item.text)
                                self.state['dialogue']='正在回答你'
                                self.gate.last_spoken = time.monotonic()
                                started[0]=True
                                if item.episode_id:
                                    self.episodes.mark_spoken(item.episode_id)
                                threading.Thread(target=self.motion_safe,args=(item.motion,valid),daemon=True).start()
                            result = await asyncio.to_thread(self.audio.play,wav,valid,on_first)
                            if played_row is not None:
                                self.conversation.finish(played_row,result.get('status')=='written_to_device')
                            first=result.get('first_write_monotonic')
                            response_ms=(round((first-item.input_finished_at)*1000) if first is not None
                                         and item.input_finished_at is not None else None)
                            self.log('playback',session_id=playback_session,role=item.role,episode_id=item.episode_id,evidence=item.evidence,
                                     purpose=item.purpose,analysis_id=item.analysis_id,turn_id=item.turn_id,
                                     input_finished_at=item.input_finished_at,response_latency_ms=response_ms,
                                     gate_reason=self.gate.reason,**result)
                            if started[0]:
                                if result.get('status')=='written_to_device':
                                    self.state['dialogue']='回答已输出，继续听你说'
                                    self.state['speaker']='整段语音已写入本体设备 · 等待现场听觉确认'
                                    self.memory.append({'kind':'role_joke','speaker_role_id':item.role,
                                        'match_id':self.events.match_id,'episode_id':item.episode_id,'text':item.text})
                                else:
                                    self.state['dialogue']='回答被打断，继续听你说'
                                    self.state['speaker']='本体语音已中断 · 未完成播放'
                        else:
                            self.log('reply_cancelled_before_play',turn_id=item.turn_id,reason=self.gate.reason)
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                    except Exception as exc:
                        self.state['dialogue']='声音播放失败，请查看设备状态'
                        self.state['speaker'] = f'失败：{type(exc).__name__}: {exc}'
                        self.log('speech_failed',session_id=playback_session,analysis_id=item.analysis_id,
                                 turn_id=item.turn_id,error=type(exc).__name__)
                    finally:
                        if played_row is not None and played_row['end'] is None:
                            self.conversation.finish(played_row,False)
                        self.speech_candidate=None
                        wav=None
                else:
                    wait_reason=self.state.get('event_reaction') if item.purpose in ('kill_reaction','death_reaction') else self.gate.reason
                    reason=(item.episode_id,item.created,wait_reason)
                    if self.last_wait_reason!=reason:
                        self.log('candidate_wait',episode_id=item.episode_id,reason=wait_reason,
                                 source_at=item.created,expires_at=item.created+20)
                        self.last_wait_reason=reason
            await asyncio.sleep(.05)

    def motion_safe(self, motion, valid):
        try:
            result=self.robot.move(motion,valid)
            status=(result or {}).get('status')
            if status in ('busy','stopped','unavailable','error','dry_run'):
                self.state['motion']='动作未完成：'+status
            else:
                self.state['motion'] = '动作指令已执行，物理效果待确认'
        except Exception as exc:
            self.state['motion'] = f'失败：{type(exc).__name__}'

    def start_mic(self):
        if self.mic_thread and self.mic_thread.is_alive():
            return
        self.mic_stop.clear()
        self.mic_thread = threading.Thread(target=self.mic_worker,daemon=True)
        self.mic_thread.start()

    async def begin_owner_turn(self, audio_metadata=None):
        if not self.gate.running or self.gate.paused:
            return None
        if audio_metadata is not None:
            self.log('voice_onset',**audio_metadata)
        self.gate.owner_speaking=True
        self.state['dialogue']='听到讲话，正在收听'
        # VAD detects sound, not an instruction to discard a turn or stop speaking.
        return self.gate.epoch

    @audio_apartment
    def mic_worker(self):
        """Full duplex AEC reference and local speech detection; no speaker identity claim."""
        try:
            d = choose_device('input',self.audio.input_device)
            rate = int(d['rate'])
            chunks = queue.Queue(maxsize=100)
            def callback(data, frames, timing, status):
                try:
                    at=time.monotonic()+timing.inputBufferAdcTime-timing.currentTime
                    chunks.put_nowait((at,data.copy(),bool(status)))
                except queue.Full:
                    pass
            self.state['microphone'] = '本体麦克风收听中 · 回声过滤 + 说话对象上下文判断'
            frontend=SpeechFrontEnd(rate,self.audio.reference)
            segmenter=UtteranceSegmenter()
            utterance_epoch=None
            last_speech_at=None
            utterance_acoustic=None
            with sd.InputStream(device=d['id'],samplerate=rate,channels=1,dtype='float32',
                                blocksize=int(rate*.02),callback=callback):
                while not self.mic_stop.is_set():
                    try:
                        at,chunk,discontinuous = chunks.get(timeout=.2)
                    except queue.Empty:
                        continue
                    if discontinuous or time.monotonic()-at>.3:
                        segmenter=UtteranceSegmenter()
                        frontend=SpeechFrontEnd(rate,self.audio.reference)
                        self.gate.owner_speaking=False
                        last_speech_at=None
                        continue
                    clean,speech,_=frontend.process(chunk,at)
                    if speech:
                        last_speech_at=at+len(chunk)/rate
                    started,data,finished=segmenter.feed(clean,speech)
                    if started:
                        audio_metadata={**frontend.metrics,'during_playback':self.audio.playing,
                                        'capture_delay_ms':round((time.monotonic()-at)*1000)}
                        utterance_acoustic=dict(audio_metadata)
                        self.gate.owner_speaking=True
                        utterance_epoch=asyncio.run_coroutine_threadsafe(
                            self.begin_owner_turn(audio_metadata),self.loop).result(timeout=1)
                    if finished:
                        self.gate.owner_speaking=False
                        if data is not None and utterance_epoch is not None and not self.mic_stop.is_set():
                            out=io.BytesIO()
                            with wave.open(out,'wb') as wav:
                                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
                                wav.writeframes((np.clip(data,-1,1)*32767).astype('<i2').tobytes())
                            asyncio.run_coroutine_threadsafe(self.owner_audio(out.getvalue(),utterance_epoch,
                                input_finished_at=last_speech_at,
                                acoustic={**(utterance_acoustic or {}),**segmenter.last_metrics}),self.loop)
                            out=None
                            data=None
        except Exception as exc:
            self.state['microphone'] = f'失败：{type(exc).__name__}: {exc}'
        finally:
            self.gate.owner_speaking=False

    async def owner_audio(self, wav, epoch, input_finished_at=None, acoustic=None):
        if not self.gate.running or self.gate.paused or epoch!=self.gate.epoch:
            return
        if acoustic and (acoustic.get('voiced_ms',1000)<240 or acoustic.get('speech_ratio',1)<.18):
            self.log('speech_rejected',reason='insufficient_speech')
            self.state['dialogue']='已过滤过短或零散的声音'
            return
        task=asyncio.current_task()
        self.owner_tasks.add(task)
        turn_id=uuid.uuid4().hex
        input_finished_at=time.monotonic() if input_finished_at is None else input_finished_at
        session=self.session
        def current():
            return self.gate.running and not self.gate.paused and epoch==self.gate.epoch and session==self.session
        async def recognize():
            with request_scope(session_id=self.session,turn_id=turn_id,phase='speech_recognition',input_finished_at=input_finished_at):
                text=await self.job(self.cloud.asr(wav))
            reason=self.conversation.rejection(text,input_finished_at,acoustic)
            if reason:
                if current():
                    self.state['dialogue']='已忽略背景声或无明确对象的片段'
                    self.log('speech_rejected',reason=reason,turn_id=turn_id)
                return ''
            # Only a stop/quiet request bypasses addressing, to retain the fast
            # emergency stop. Resume/end/pause must pass semantic addressing.
            action=self.local_voice_action(text)
            if current() and action=='quiet':
                await self.control(action)
                return ''
            return text
        recognition=asyncio.create_task(recognize())
        try:
            self.state['dialogue']='正在识别你说的话'
            # Recognition overlaps across utterances; conversation memory and replies
            # are committed in capture order, even if a later ASR finishes first.
            async with self.owner_turn_lock:
                self.owner_task=task
                text=await recognition
                if current() and text.strip():
                    self.state['last_heard']=text[:160]
                    await self.owner_text(text,turn_id=turn_id,input_finished_at=input_finished_at,
                                          audio_context=acoustic or {})
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.state['dialogue']='语音识别失败，请再说一次'
            self.log('asr_failed',error=type(exc).__name__)
        finally:
            if not recognition.done():
                recognition.cancel()
            await asyncio.gather(recognition,return_exceptions=True)
            self.owner_tasks.discard(task)
            if self.owner_task is task:
                self.owner_task=None

    @staticmethod
    def local_voice_action(text):
        # Fast stop path only matches a complete request, not a quoted substring.
        compact=re.sub(r'[\s，。！？,.!?]','',text)
        if re.fullmatch(r'(?:请|麻烦)?(?:先)?(?:安静|别说话|别说了|别再说了|不要说话|停一下|停|闭嘴)(?:一下|一会儿|会儿|吧|了|好吗|行吗)?',compact):
            return 'quiet'
        if compact in ('结束陪玩','结束会话','结束这次陪玩'):
            return 'end'
        if compact in ('继续陪我','可以说话','恢复说话'):
            return 'unquiet'
        if compact in ('暂停收听','暂停采集','关闭麦克风'):
            return 'pause'
        return None

    def acknowledge_name(self,text,turn_id,input_finished_at,*,failed=False):
        # A real call deserves an audible acknowledgement even without a model
        # answer. It is a direct reply, so combat and proactive cooldown do not apply.
        vent=self.gate.relaxed and is_game_vent(text)
        answer=('这波听着就憋屈，想吐槽就说，我听着。' if vent else
                '刚才的问题没处理好，你再说一次？' if failed else '在呢，你说。')
        self.conversation.remember('user',text)
        self.conversation.remember('assistant',answer,'queued')
        self.state['dialogue']='听到你叫我，准备回应'
        self.state['last_reply']=answer
        self.pending.append(Candidate(answer,self.role,self.gate.epoch,time.monotonic(),[],False,'neutral',
                                      purpose='name_call',turn_id=turn_id,input_finished_at=input_finished_at))

    async def owner_text(self,text,turn_id=None,input_finished_at=None,audio_context=None):
        if not self.gate.running or self.gate.paused:
            return
        turn_id=turn_id or uuid.uuid4().hex
        called,request=name_call(text,self.preferences.name)
        vent=self.gate.relaxed and is_game_vent(text)
        wants_reply=called or vent
        action=self.local_voice_action(request if called else text)
        if action and (called or audio_context is None or action=='quiet'):
            return await self.control(action)
        if called and request in ('','呀','啊','在吗','你在吗','在不在','说话','说句话'):
            self.acknowledge_name(text,turn_id,input_finished_at)
            return
        epoch=self.gate.epoch
        stage='model_reply'
        try:
            self.state['dialogue']='正在想怎么回答'
            with request_scope(session_id=self.session,turn_id=turn_id,phase='owner_dialogue',input_finished_at=input_finished_at):
                turn=await self.job(self.cloud.owner_turn(self.role,text,self.latest,self.memory_context(text),
                                                         self.identities.snapshot(),self.preferences.model_dump(),
                                                         {'quiet':self.gate.quiet,'running':self.gate.running,
                                                          'volume':self.audio.volume,'role':self.role,
                                                          'input_source':'microphone' if audio_context is not None else 'manual',
                                                          'acoustic_hints':audio_context,
                                                          **self.conversation.snapshot(input_finished_at)}))
            if epoch!=self.gate.epoch or self.gate.paused or not self.gate.running:
                return
            action=turn.action
            stage='apply_'+action
            self.log('owner_intent',action=action)
            if action=='ignore':
                if wants_reply:
                    self.acknowledge_name(text,turn_id,input_finished_at,failed=True)
                    return
                self.state['dialogue']='这句话未判断为对我说，继续听你说'
                self.log('speech_rejected',reason='not_addressed_to_assistant',turn_id=turn_id)
                return
            self.conversation.remember('user',text)
            if action in ('quiet','unquiet','pause','end'):
                return await self.control(action)
            if action=='switch_role':
                return await self.control('role',turn.target_role or ('anao' if self.role=='aqi' else 'aqi'))
            if action in ('volume_down','volume_up'):
                return await self.control('volume',self.audio.volume+(-.1 if action=='volume_down' else .1))
            if action=='confirm_identity':
                owner=self.identities.context() or {}
                friends=([f.model_dump() for f in turn.friends] if turn.friends is not None
                         else [{'name':f['name'],'nickname':f['nickname']} for f in owner.get('friends',[])])
                return await self.confirm_identity(self.identities.match_id,turn.player_name or owner.get('name'),friends)
            if action=='report_identity':
                return await self.report_identity(turn.reported_identity)
            if action=='correct':
                await self.halt('主人纠正了刚才的判断')
                epoch=self.gate.epoch
                self.facts_revision+=1
                previous=self.latest
                if previous and previous.get('episode_id'):
                    self.episodes.revoke(previous['episode_id'])
                self.memory=deque((m for m in self.memory if not (
                    m.get('match_id')==self.events.match_id and m['kind'] in ('inference','observed_fact')
                    and m.get('situation')==previous)),maxlen=30)
                self.latest=None
                self.memory.append({'kind':'correction','match_id':self.events.match_id,'text':text})
            else:
                self.memory.append({'kind':'owner_statement','match_id':self.events.match_id,'text':text})
            reply=turn.reply
            if reply and reply.text:
                problem=reply_problem(reply.text,self.conversation.snapshot()['recent_replies'],text)
                if problem:
                    self.log('reply_rejected',reason=problem,turn_id=turn_id)
                    if wants_reply:
                        self.acknowledge_name(text,turn_id,input_finished_at,failed=True)
                        return
                    self.state['dialogue']='已过滤重复或空泛回复，继续收听'
                    return
                self.conversation.remember('assistant',reply.text,'queued')
                self.state['dialogue']='回答已准备好，等待开口'
                self.state['last_reply']=reply.text
                self.pending.append(Candidate(reply.text,self.role,epoch,time.monotonic(),reply.evidence,False,reply.motion,
                                                  turn_id=turn_id,input_finished_at=input_finished_at))
            elif wants_reply:
                self.acknowledge_name(text,turn_id,input_finished_at,failed=True)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.state['dialogue']='这次回答失败，请再说一次'
            self.state['cloud']='对话未完成：'+type(exc).__name__
            self.log('dialogue_failed',error=type(exc).__name__,error_code=dialogue_error_code(exc),
                     stage=stage,turn_id=turn_id)
            if wants_reply and epoch==self.gate.epoch and self.gate.running and not self.gate.paused:
                self.acknowledge_name(text,turn_id,input_finished_at,failed=True)

    async def diagnostic(self, kind):
        if self.clearing_data:
            raise ValueError('正在清除本地数据，请稍候')
        if self.diagnostic_lock.locked():
            raise ValueError('另一项本体诊断正在进行')
        async with self.diagnostic_lock:
            return await self._diagnostic(kind)

    async def _diagnostic(self, kind):
        if self.gate.running:
            raise ValueError('请先结束陪玩再运行独立硬件诊断')
        epoch=self.gate.epoch
        if kind=='audio':
            wav=await asyncio.to_thread(sapi_wav,'你好，我是 Reachy。现在测试本体声音，游戏陪玩还没有开始。')
            result=await asyncio.to_thread(self.audio.play,wav,lambda:epoch==self.gate.epoch)
            self.state['speaker']=('本体设备写入完成，等待听觉确认' if result['status']=='written_to_device'
                                   else '声音测试已中断，尚未完整播放')
        elif kind=='microphone':
            result,data,rate=await asyncio.to_thread(self.audio.record_probe,3)
            self.state['microphone']='已读取本体输入信号，主人语音识别尚未验证'
        elif kind=='motion':
            result=await asyncio.to_thread(self.robot.move,'nod',lambda:epoch==self.gate.epoch)
            self.state['motion']='已发小幅动作指令，待物理确认'
        else:
            raise ValueError('未知诊断')
        with (self.root/'evidence'/'hardware.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps({'kind':kind,**result},ensure_ascii=False)+'\n')
        self.log('diagnostic',kind_name=kind,**result)
        return result
