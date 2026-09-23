"""Bounded evidence-backed episodes. Time proximity alone never merges processes."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import uuid


@dataclass
class Episode:
    id: str
    match_id: str
    started: float
    updated: float
    segment: tuple
    frames: list = field(default_factory=list)
    events: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    inferences: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    contribution: str = ''
    outcome: str = ''
    revision: int = 0
    ended: bool = False
    spoken: bool = False
    revoked: bool = False

    def summary(self):
        return deepcopy(dict(kind='episode_summary',episode_id=self.id,match_id=self.match_id,
            started=self.started,updated=self.updated,ended=self.ended,spoken=self.spoken,
            revoked=self.revoked,observed_fact=self.observations,inference=self.inferences,
            unknowns=self.unknowns,contribution=self.contribution,outcome=self.outcome,
            event_ids=[e['event_key'] for e in self.events],
            evidence_media_available=bool(self.frames)))


class Episodes:
    def __init__(self,max_summaries=20,max_frames=8,max_bytes=8*1024*1024):
        self.items=deque(maxlen=max_summaries)
        self.active=None
        self.max_frames=max_frames
        self.max_bytes=max_bytes

    @staticmethod
    def segment(frame):
        return (frame.window_id,frame.segment)

    def detach(self):
        # Leaving the game, a camera cut, or a match boundary breaks continuity.
        if self.active:
            self.active.ended=True
            self.active.frames.clear()
        self.active=None

    def prepare(self,match_id,frames):
        episode=self.active
        if not frames:
            return [],None
        now=frames[-1].at
        if episode and (episode.match_id!=match_id or episode.segment!=self.segment(frames[-1])
                        or now-episode.updated>12 or now<episode.updated or episode.revoked):
            self.detach()
            episode=None
        if not episode:
            return list(frames),None
        episode.frames=[f for f in episode.frames if now-f.at<=60]
        current_ids={f.id for f in frames}
        anchors=[f for f in episode.frames if f.id not in current_ids]
        if len(anchors)>3:
            anchors=[anchors[0],anchors[len(anchors)//2],anchors[-1]]
        combined=sorted(anchors+list(frames),key=lambda f:f.at)
        return combined,episode.summary()

    def record(self,match_id,current_frames,evidence_frames,events,situation):
        at=current_frames[-1].at
        previous=self.active
        current_ids={f.id for f in current_frames}
        previous_ids={f.id for f in previous.frames} if previous else set()
        basis=set(situation.get('continuity_evidence',[]))
        continuation=(previous is not None and not previous.revoked
            and previous.match_id==match_id and previous.segment==self.segment(current_frames[-1])
            and 0<=at-previous.updated<=12
            and situation.get('continuation_of')==previous.id
            and bool(basis & previous_ids) and bool(basis & (current_ids-previous_ids)))
        if continuation:
            episode=previous
        else:
            self.detach()
            if not situation.get('meaningful'):
                return None
            episode=Episode(str(uuid.uuid4()),match_id,current_frames[0].at,at,
                            self.segment(current_frames[-1]))
            self.items.append(episode)
            self.active=episode
        episode.updated=at
        new_events={e['event_key'] for e in events}-{e['event_key'] for e in episode.events}
        if not continuation or situation.get('supersedes_previous') or new_events:
            episode.revision+=1
        episode.ended=situation.get('process_ended',False)
        episode.contribution=situation.get('contribution','')
        episode.outcome=situation.get('outcome','')
        for name,limit in [('observations',6),('inferences',4)]:
            by_text={c['text']:c for c in getattr(episode,name)}
            by_text.update({c['text']:deepcopy(c) for c in situation.get(name,[])})
            setattr(episode,name,list(by_text.values())[-limit:])
        episode.unknowns=list(dict.fromkeys(episode.unknowns+situation.get('unknowns',[])))[-8:]
        by_event={e['event_key']:e for e in episode.events}
        by_event.update({e['event_key']:deepcopy(e) for e in events})
        episode.events=list(by_event.values())[-30:]
        by_id={f.id:f for f in (episode.frames+list(evidence_frames)) if at-f.at<=60}
        episode.frames=sorted(by_id.values(),key=lambda f:f.at)
        # Evenly retain anchors rather than keeping an unbounded raw clip.
        if len(episode.frames)>self.max_frames:
            n=len(episode.frames)
            episode.frames=[episode.frames[round(i*(n-1)/(self.max_frames-1))] for i in range(self.max_frames)]
        while episode.frames and sum(len(f.jpeg) for f in episode.frames)>self.max_bytes:
            episode.frames.pop(0)
        return episode

    def valid(self,episode_id,revision,allow_spoken=False):
        item=next((e for e in self.items if e.id==episode_id),None)
        return bool(item and not item.revoked and item.revision==revision and (allow_spoken or not item.spoken))

    def mark_spoken(self,episode_id):
        for item in self.items:
            if item.id==episode_id:
                item.spoken=True

    def revoke(self,episode_id):
        for item in self.items:
            if item.id==episode_id:
                item.revoked=True
                item.frames.clear()
                item.observations=[]
                item.inferences=[]
                item.contribution=item.outcome=''
                item.unknowns=['主人已撤回该底稿，不再引用旧判断']

    def revoke_match(self,match_id):
        for item in self.items:
            if item.match_id==match_id:
                self.revoke(item.id)

    def summaries(self,limit=20):
        return [item.summary() for item in list(self.items)[-limit:]]

    def clear(self):
        self.items.clear()
        self.active=None
