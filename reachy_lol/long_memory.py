"""Persistent public game vocabulary; conversation and match facts are not saved."""
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from .match_research import MatchKnowledge, research_match

# Local vocabulary only. Mechanics always come from versioned official records.
ITEM_ALIASES = {
    '3157':['金身','中娅','沙漏'], '3089':['帽子','大帽','大帽子'],
    '3124':['羊刀'], '3153':['破败'], '3031':['无尽'], '3071':['黑切'],
    '3078':['三相'], '3116':['冰杖'], '3083':['狂徒'], '3026':['复活甲','春哥甲'],
    '3156':['大饮魔刀','饮魔刀'], '3155':['小饮魔刀'], '3161':['青龙刀'],
    '3139':['水银刀'], '3140':['水银饰带','水银'], '3006':['攻速鞋'],
    '3047':['布甲鞋','铁板鞋'], '3111':['水银鞋'], '3158':['CD鞋','明朗鞋'],
    '3020':['法穿鞋'], '3135':['法穿棒','虚空杖'], '3134':['锯齿'],
    '3142':['幽梦'], '3814':['夜之锋刃','夜刃'], '6694':['赛瑞尔达','减速穿甲弓'],
    '6695':['巨蛇之牙','蛇牙'], '6698':['亵渎九头蛇','亵渎'],
    '6699':['电震涡流剑','感电'], '3036':['大穿甲弓','多米尼克'],
    '3033':['凡性的提醒','重伤弓'], '3075':['反甲'], '3024':['小冰心'],
    '3110':['冰心'], '3068':['日炎'], '3053':['血手'], '3508':['吸蓝刀'],
    '3094':['火炮'], '3085':['分裂弓','飓风'], '3072':['饮血剑','饮血'],
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class LongMemory:
    def __init__(self, root):
        self.path=Path(root)/'memory'/'equipment.json'
        self.data={'version':1,'items':{},'champions':{},'sources':[], 'fetched_at':None}
        try:
            saved=json.loads(self.path.read_text(encoding='utf8'))
            if saved.get('version')==1 and isinstance(saved.get('items'),dict):
                self.data=saved
        except (OSError, ValueError, AttributeError):
            pass
        self.lock=asyncio.Lock()
        self.error=None

    def stale(self):
        try:
            return (datetime.now(timezone.utc)-datetime.fromisoformat(self.data['fetched_at'])).total_seconds()>86400
        except (KeyError, TypeError, ValueError):
            return True

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='equipment-',suffix='.tmp',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as output:
                json.dump(self.data,output,ensure_ascii=False,indent=2)
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)

    async def refresh(self):
        async with self.lock:
            if not self.stale():return
            knowledge=await research_match('public-catalog',[])
            if not knowledge.items:
                self.error='refresh_failed_using_local_memory'
                return
            for id,item in knowledge.items.items():
                # Keep user vocabulary across catalog updates; deleted IDs are not revived.
                old=self.data['items'].get(id,{})
                item['aliases']=list(dict.fromkeys(item['aliases']+old.get('aliases',[])+ITEM_ALIASES.get(id,[])))
                item['alias_sources']=list(dict.fromkeys(item['alias_sources']+['local_equipment_vocabulary']))
            self.data={'version':1,'items':knowledge.items,'champions':knowledge.catalog,
                       'sources':knowledge.sources,'fetched_at':utcnow()}
            await asyncio.to_thread(self.save)
            self.error=None

    def context(self,text='',item_ids=()):
        k=MatchKnowledge('public',[],{},self.data['items'],self.data['sources'],[])
        hits=k.resolve(text)
        wanted=set(map(str,item_ids))|{c['id'] for h in hits for c in h['candidates'] if c['kind']=='item'}
        return {'kind':'local_equipment_memory','scope':'persistent_public_knowledge',
                'fetched_at':self.data['fetched_at'],'stale':self.stale(),'not_live_evidence':True,
                'term_matches':hits,'item_details':[v for key,v in self.data['items'].items() if key in wanted][:16],
                'rule':'本地长期装备词典，按当前问题/本局推荐装备检索；昵称持久保留，数值随版本刷新，过期时不声称是当前数值。'}

    def resolve_champion(self,name):
        if not name:return None
        matches=[h for h in self.data.get('champions',{}).values()
                 if name.casefold() in [str(v).casefold() for v in h.get('aliases',[])]]
        return matches[0] if len(matches)==1 else None

    def summary(self):
        return {'items':len(self.data['items']),'champions':len(self.data.get('champions',{})),
                'fetched_at':self.data['fetched_at'],'stale':self.stale(),'error':self.error,
                'persistent':True}
