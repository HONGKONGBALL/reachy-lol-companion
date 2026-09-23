"""Session-scoped identity; never infer party membership from team membership."""
from copy import deepcopy
from pydantic import BaseModel,ConfigDict,Field


class ReportedFriend(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    nickname: str=Field(min_length=1,max_length=40)
    champion: str | None=Field(default=None,min_length=1,max_length=60)


class OwnerReport(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    champion: str=Field(min_length=1,max_length=60)
    team: str | None=Field(default=None,min_length=1,max_length=20)
    friends: list[ReportedFriend]=Field(default_factory=list,max_length=4)


def aliases(player):
    values = [player.get('riotId'), player.get('summonerName')]
    if player.get('riotIdGameName') and player.get('riotIdTagLine'):
        values.append(player['riotIdGameName']+'#'+player['riotIdTagLine'])
    return {v for v in values if isinstance(v,str) and v.strip()}


class Identity:
    def __init__(self):
        self.match_id = None
        self.roster = []
        self.owner = None
        self.confirmed_name = None
        self.friends = {}  # Explicit owner confirmation only; in memory only.
        self.fresh = False
        self.reported_owner = None

    def update(self, data, match_id):
        # Recovery requires a fresh mapping, never a guess from spoken names.
        self.reported_owner = None
        if self.match_id != match_id:
            self.owner = None
            self.confirmed_name = None
            self.match_id = match_id
        self.roster = [dict(name=p.get('riotId') or p.get('summonerName'),
                            aliases=sorted(aliases(p)), champion=p.get('championName'),
                            team=p.get('team')) for p in data.get('allPlayers',[])
                       if aliases(p)][:32]
        # CN Live Client events use a bare Riot game name, while activePlayer
        # and allPlayers use name#tag. Add a bare alias only when unambiguous
        # within this roster; never assign same-name players' kills by guessing.
        bare_names={}
        for player in self.roster:
            for name in {a.split('#',1)[0] for a in player['aliases']}:
                bare_names.setdefault(name,[]).append(player)
        for name,players in bare_names.items():
            if len(players)==1 and name not in players[0]['aliases']:
                players[0]['aliases'].append(name)
        names = {self.confirmed_name} if self.confirmed_name else aliases(data.get('activePlayer',{}))
        matching = [p for p in self.roster if names.intersection(p['aliases'])]
        self.owner = (dict(matching[0],source='owner_confirmed' if self.confirmed_name else 'live_client',
                           match_id=match_id) if len(matching)==1 else None)
        self.fresh = True
        return self.context()

    def confirm(self, match_id, name, friends):
        if not self.fresh or match_id != self.match_id:
            raise ValueError('对局信息已变化或断开，请刷新身份后重新确认')
        matching = [p for p in self.roster if name in p['aliases']]
        if len(matching)!=1:
            raise ValueError('请选择本局唯一的玩家身份')
        owner = matching[0]
        confirmed = {}
        for friend in friends:
            rows = [p for p in self.roster if friend['name'] in p['aliases']]
            if len(rows)!=1 or rows[0]['name']==owner['name']:
                raise ValueError('朋友必须是本局其他玩家，不能选择自己')
            if not owner['team'] or rows[0]['team']!=owner['team']:
                raise ValueError('组排朋友必须是已确认的同队玩家')
            confirmed[rows[0]['name']] = friend['nickname'].strip() or rows[0]['name']
        # Replace confirmations for this roster; preserve other-session-match friends.
        current_aliases = {a for p in self.roster for a in p['aliases']}
        self.friends = {k:v for k,v in self.friends.items() if k not in current_aliases}
        self.friends.update(confirmed)
        self.confirmed_name = name
        self.owner = dict(owner,source='owner_confirmed',match_id=match_id)
        return self.context()

    def disconnect(self):
        self.fresh = False
        self.owner = None

    def context(self):
        if not self.owner or not self.fresh:
            return deepcopy(self.reported_owner)
        result = deepcopy(self.owner)
        result['friends'] = [dict(name=p['name'],nickname=self.friends[p['name']],
                                  champion=p['champion'],team=p['team'],source='owner_confirmed')
                             for p in self.roster if p['name'] in self.friends
                             and p['name']!=result['name'] and p['team']==result['team']]
        return result

    def snapshot(self):
        return deepcopy(dict(match_id=self.match_id,fresh=self.fresh,owner=self.context(),
                             roster=self.roster if self.fresh else [],
                             status=('已确认本局身份' if self.owner and self.fresh else
                                     '主人自报 · 未经接口核实' if self.reported_owner else '身份待确认')))

    def report(self,report,scope):
        if self.fresh:
            raise ValueError('当前已有本局名册，请从名册确认本人和朋友')
        self.reported_owner=dict(name=None,aliases=[],champion=report.champion,team=report.team,
                                 source='owner_reported',match_id=scope,verified_against_roster=False,
                                 friends=[dict(**f.model_dump(),source='owner_reported') for f in report.friends])
        return self.context()

    def clear_report(self):
        self.reported_owner=None
