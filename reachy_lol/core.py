from __future__ import annotations
import time
import uuid
from collections import deque
from dataclasses import dataclass, field


def boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    return None


@dataclass
class Frame:
    id: str
    at: float
    jpeg: bytes
    game_time: float | None = None
    window_id: int | None = None
    segment: int = 0
    width: int | None = None
    height: int | None = None


class FrameBuffer:
    def __init__(self, seconds=20, max_bytes=128 * 1024 * 1024):
        self.frames = deque()
        self.seconds, self.max_bytes = seconds, max_bytes

    def add(self, frame):
        self.frames.append(frame)
        self.prune(frame.at)

    def prune(self, now):
        while self.frames and (now-self.frames[0].at > self.seconds or
                               sum(len(f.jpeg) for f in self.frames) > self.max_bytes):
            self.frames.popleft()

    def sample(self, now, seconds=8, count=4):
        self.prune(now)
        frames = [f for f in self.frames if f.at >= now-seconds]
        if len(frames) <= count:
            return frames
        return [frames[round(i*(len(frames)-1)/(count-1))] for i in range(count)]

    def clear(self):
        self.frames.clear()


class Events:
    """Baseline every reconnect; never replay a historical event as fresh."""
    def __init__(self):
        self.match_id = str(uuid.uuid4())
        self.seen = set()
        self.last_time = None
        self.connected = False

    def ingest(self, data):
        game_time = data.get('gameData', {}).get('gameTime')
        if not isinstance(game_time, (int, float)):
            raise ValueError('gameTime missing')
        new_match = self.last_time is not None and game_time < self.last_time - 5
        if new_match:
            self.match_id = str(uuid.uuid4())
            self.seen.clear()
            self.connected = False
        items = data.get('events', {}).get('Events', [])
        fresh = []
        for item in items:
            key = str(item.get('EventID', (item.get('EventName'), item.get('EventTime'),
                                          item.get('KillerName'), item.get('VictimName'))))
            if self.connected and key not in self.seen:
                at = item.get('EventTime')
                if isinstance(at, (int, float)) and 0 <= game_time-at <= 8:
                    event=dict(item, source='live_client', match_id=self.match_id,
                               event_key=f'{self.match_id}:live_client:{key}')
                    if 'Stolen' in event:
                        event['Stolen']=boolean(event['Stolen'])
                    fresh.append(event)
            self.seen.add(key)
        self.last_time, self.connected = game_time, True
        return fresh, new_match


@dataclass
class Gate:
    running: bool = False
    paused: bool = False
    quiet: bool = False
    owner_speaking: bool = False
    safe_since: float | None = None
    last_local: float = -1000
    visual_at: float = -1000
    visual_safe: bool = False
    visual_continuity_at: float = -1000
    last_spoken: float = -1000
    epoch: int = 0
    reason: str = '未开始'
    cooldown: float = 20
    robot_ready: bool = False
    robot_at: float = -1000
    game_present: bool | None = None
    game_presence_at: float = -1000

    def invalidate(self, reason):
        self.epoch += 1
        self.safe_since = None
        self.reason = reason

    def observe(self, now, safe):
        self.last_local = now
        if safe:
            if self.safe_since is None:
                self.safe_since = now
        else:
            self.safe_since = None

    def allowed(self, now, proactive=True):
        checks = [
            (self.running, '未开始'), (not self.paused, '采集已暂停'),
            (self.robot_ready and now-self.robot_at<5, '本体连接未就绪或已过期'),
            (not (self.owner_speaking and proactive), '讲话期间暂缓主动评论'),
            (not (self.quiet and proactive), '已安静'),
        ]
        for ok, reason in checks:
            if not ok:
                self.reason = reason
                return False
        if self.game_present is False and 0<=now-self.game_presence_at<1.5:
            self.reason='等待你说话' if proactive else '可交流'
            return not proactive
        checks = [
            (now-self.last_local < 1.2, '本地状态过期'),
            (self.safe_since is not None and now-self.safe_since >= 2, '等待持续安全线索'),
            (self.visual_safe and (0<=now-self.visual_at<=6 or
                (0<=now-self.visual_at<=20 and self.visual_continuity_at>=self.visual_at
                 and 0<=now-self.visual_continuity_at<1.2)), '画面安全证据不足或过期'),
            (not proactive or now-self.last_spoken >= self.cooldown, '主动冷却'),
        ]
        for ok, reason in checks:
            if not ok:
                self.reason = reason
                return False
        self.reason = '可交流'
        return True


@dataclass
class Candidate:
    text: str
    role: str
    epoch: int
    created: float
    evidence: list[str] = field(default_factory=list)
    proactive: bool = True
    motion: str = 'nod'
    episode_id: str | None = None
    episode_revision: int = 0
    purpose: str = 'comment'
    analysis_id: str | None = None
    turn_id: str | None = None
    input_finished_at: float | None = None

    def valid(self, gate, role, now):
        return self.epoch == gate.epoch and self.role == role and now-self.created <= 20
