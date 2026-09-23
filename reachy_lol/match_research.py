"""Public web lookup and match-scoped vocabulary. No player names leave the PC."""
import asyncio
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import re
import httpx

HERO_INDEX='https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js'
ITEM_INDEX='https://game.gtimg.cn/images/lol/act/img/js/items/items.js'
ALIAS_PAGE='https://k.sina.cn/article_7056330953_1a49710c900100mwfx.html?from=game'
QIYANA_PAGE='https://gl.ali213.net/html/2025-5/1660647.html'


def plain(value, limit=160):
    return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]+>',' ',str(value or '')))).strip()[:limit]


def terms(*values):
    result=[]
    for value in values:
        for term in re.split(r'[,，、;；]',str(value or '')):
            term=term.strip()
            if 2<=len(term)<=24 and re.fullmatch(r'[\w\u4e00-\u9fff· .-]+',term) and term not in result:
                result.append(term)
    return result[:30]


class PageText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('p','div','br','li'):self.parts.append('\n')

    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','div','li'):self.parts.append('\n')

    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def add_community_aliases(html, records, source):
    """Extract explicit name—alias mappings; no arbitrary page prose in prompts.

    Old community sources contribute names only, never current mechanics/stats.
    An alias may map to several records; the resolver preserves that ambiguity.
    """
    parser=PageText();parser.feed(html)
    for line in ''.join(parser.parts).splitlines():
        split=re.split(r'[—–－]',line.strip(),maxsplit=1)
        if len(split)!=2 or len(split[0])>50 or len(split[1])>100:continue
        left,right=split
        aliases=terms(re.split(r'[（(。！!]',right)[0])
        for record in records:
            if any(name and len(name)>=2 and name in left for name in (record['name'],record.get('title'))):
                record['aliases']=list(dict.fromkeys(record['aliases']+aliases))[:30]
                if aliases and source not in record['alias_sources']:record['alias_sources'].append(source)


def mentioned(alias, text):
    if alias.isascii():
        return bool(re.search(r'(?<![a-zA-Z0-9])'+re.escape(alias)+r'(?![a-zA-Z0-9])',text,re.I))
    return alias in text


class MatchKnowledge:
    def __init__(self, match_id, lineup, champions, items, sources, errors):
        self.match_id=match_id;self.lineup=lineup
        self.champions=champions;self.items=items
        self.sources=sources;self.errors=errors
        self.catalog={}
        self.fetched_at=datetime.now(timezone.utc).isoformat()

    def resolve(self,text):
        hits={}
        for kind,records in (('champion',self.champions.values()),('item',self.items.values())):
            for record in records:
                for alias in record['aliases']:
                    if mentioned(alias,text):
                        hit={'kind':kind,'id':record['id'],'name':record['name'],
                             'source':record['source'],'alias_sources':record['alias_sources']}
                        candidates=hits.setdefault(alias,[])
                        if not any(c['kind']==kind and c['name']==record['name'] for c in candidates):candidates.append(hit)
        # Prefer the longest overlapping phrase (大饮魔刀 must not become 饮魔刀).
        keys=sorted(hits,key=len,reverse=True)
        return [{'spoken':key,'candidates':hits[key][:5],'ambiguous':len(hits[key])>1}
                for key in keys if not any(key!=other and key in other for other in keys)][:10]

    def context(self,text='',owner_champion=None):
        hits=self.resolve(text)
        wanted={candidate['id'] for h in hits for candidate in h['candidates'] if candidate['kind']=='champion'}
        wanted.update(h['id'] for h in self.champions.values() if owner_champion in (h['name'],h.get('title')))
        return {'kind':'match_web_reference','match_id':self.match_id,'fetched_at':self.fetched_at,
                'scope':'current_match_only','not_live_evidence':True,
                'lineup':self.lineup,
                'champions':[{'id':h['id'],'name':h['name'],'title':h.get('title'),
                              'aliases':h['aliases'][:18],'roles':h.get('roles',[])} for h in self.champions.values()],
                'term_matches':hits,
                'champion_details':[{k:v for k,v in self.champions[id].items() if k in ('id','name','spells','source')}
                                    for id in sorted(wanted)[:3]],
                'item_details':[{k:v for k,v in item.items() if k in ('id','name','description','source','aliases')}
                                for item in self.items.values() if item['id'] in {
                                    c['id'] for h in hits for c in h['candidates'] if c['kind']=='item'}][:6],
                'sources':self.sources,'partial_errors':self.errors,
                'rule':'网页仅供理解英雄/装备/外号，不证明本局出装、技能施放、位置或战果；歧义须澄清，资料版本不等于本局已核实版本。'}

    def summary(self):
        return {'match_id':self.match_id,'status':'partial' if self.errors else 'ready',
                'champion_count':len(self.champions),'item_count':len(self.items),
                'alias_count':sum(len(x['aliases']) for x in [*self.champions.values(),*self.items.values()]),
                'sources':self.sources,'errors':self.errors,'fetched_at':self.fetched_at}


async def research_match(match_id, lineup, client=None):
    """Lookup official catalogs + explicit community aliases once per match.

    Fixed public HTTPS sources, bounded responses/concurrency, no model-key reuse.
    Only the ten public champion/team names are accepted as input.
    """
    owns=client is None
    if owns:client=httpx.AsyncClient(timeout=8,follow_redirects=False)
    sources=[];errors=[];semaphore=asyncio.Semaphore(4)
    async def get(url,as_json=True):
        try:
            async with semaphore:
                async with client.stream('GET',url) as response:
                    response.raise_for_status();parts=[];size=0
                    async for part in response.aiter_bytes():
                        size+=len(part)
                        if size>4*1024*1024:raise ValueError('public reference too large')
                        parts.append(part)
                    raw=b''.join(parts)
                    if as_json:
                        import json
                        data=json.loads(raw)
                    else:data=raw.decode('utf8',errors='replace')
                    sources.append({'url':url,'version':plain(data.get('version'),24) if isinstance(data,dict) else None,
                                    'published':plain(data.get('fileTime'),32) if isinstance(data,dict) else 'community_aliases_only'})
                    return data
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            errors.append({'url':url,'error':type(exc).__name__});return {} if as_json else ''
    try:
        hero_data,item_data,alias_html=await asyncio.gather(get(HERO_INDEX),get(ITEM_INDEX),get(ALIAS_PAGE,False))
        champions={};items={};matched=[];catalog={}
        for hero in hero_data.get('hero',[]):
            id=str(hero.get('heroId',''))
            if not id.isdigit():continue
            catalog[id]={'id':id,'name':plain(hero.get('name'),40),'title':plain(hero.get('title'),40),
                         'key':plain(hero.get('alias'),40),
                         'aliases':terms(hero.get('name'),hero.get('title'),hero.get('alias'),hero.get('keywords'))}
        for entry in lineup[:20]:
            name=entry.get('champion','')
            hero=next((h for h in hero_data.get('hero',[]) if str(name).casefold() in
                       [v.casefold() for v in terms(h.get('name'),h.get('title'),h.get('alias'),h.get('keywords'))]),None)
            if not hero:
                matched.append({'champion':name,'team':entry.get('team'),'resolved':False});continue
            id=str(hero.get('heroId',''))
            if not id.isdigit():continue
            champions[id]={'id':id,'name':plain(hero.get('name'),40),'title':plain(hero.get('title'),40),
                           'roles':[plain(x,20) for x in hero.get('roles',[])][:3],
                           'aliases':terms(hero.get('name'),hero.get('title'),hero.get('alias'),hero.get('keywords')),
                           'source':HERO_INDEX,'alias_sources':[],'spells':[]}
            matched.append({'champion':hero['name'],'team':entry.get('team'),'hero_id':id,'resolved':True})
        for item in item_data.get('items',[])[:1500]:
            id=str(item.get('itemId',''))
            if not id.isdigit():continue
            items[id]={'id':id,'name':plain(item.get('name'),50),
                       'aliases':terms(item.get('name'),item.get('keywords')),
                       'description':plain(item.get('description') or item.get('plaintext'),1800),
                       'version':plain(item_data.get('version'),30),
                       'combine_price':item.get('price'),
                       'source':ITEM_INDEX,'alias_sources':[]}
        add_community_aliases(alias_html,[*champions.values(),*items.values()],ALIAS_PAGE)
        ids=list(champions)
        details=await asyncio.gather(*(get(f'https://game.gtimg.cn/images/lol/act/img/js/hero/{id}.js') for id in ids))
        for id,detail in zip(ids,details):
            champions[id]['spells']=[{'slot':plain(s.get('spellKey'),10),'name':plain(s.get('name'),35),
                                     'description':plain(s.get('dynamicDescription') or s.get('description'),100)}
                                    for s in detail.get('spells',[])[:6]]
        if '246' in champions:
            html=await get(QIYANA_PAGE,False)
            if '奇亚娜' in html and '盘子妈' in html:
                champions['246']['aliases'].append('盘子妈');champions['246']['alias_sources'].append(QIYANA_PAGE)
        if len(champions)<len({p.get('champion') for p in lineup}):
            errors.append({'error':'unresolved_champions'})
        knowledge=MatchKnowledge(match_id,matched,champions,items,sources,errors)
        knowledge.catalog=catalog
        return knowledge
    finally:
        if owns:await client.aclose()
