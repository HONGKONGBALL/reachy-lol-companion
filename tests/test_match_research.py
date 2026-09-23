import asyncio
import json
from unittest.mock import AsyncMock
import httpx
from reachy_lol.match_research import research_match, MatchKnowledge, HERO_INDEX, ITEM_INDEX, ALIAS_PAGE
from reachy_lol.runtime import Runtime


def fixture_transport(calls, fail_items=False):
    def handle(request):
        calls.append(str(request.url))
        assert 'authorization' not in request.headers
        if str(request.url)==HERO_INDEX:
            return httpx.Response(200,json={'version':'test','hero':[
                {'heroId':'246','name':'元素女皇','title':'奇亚娜','alias':'Qiyana','keywords':'元素女皇,奇亚娜,qyn','roles':['assassin']},
                {'heroId':'1','name':'黑暗之女','title':'安妮','alias':'Annie','keywords':'安妮,火女','roles':['mage']}]})
        if str(request.url)==ITEM_INDEX:
            if fail_items:return httpx.Response(503)
            return httpx.Response(200,json={'items':[
                {'itemId':'3157','name':'中娅沙漏','keywords':'中娅沙漏,金身','plaintext':'暂时凝滞'},
                {'itemId':'223157','name':'中娅沙漏','keywords':'中娅沙漏,金身'},
                {'itemId':'3089','name':'灭世者的死亡之帽','keywords':'灭世者的死亡之帽'},
                {'itemId':'3124','name':'鬼索的狂暴之刃','keywords':'羊刀'},
                {'itemId':'9999','name':'未提及的装备','keywords':'不该塞进对话'}]})
        if str(request.url)==ALIAS_PAGE:
            return httpx.Response(200,text='<p>灭世者的死亡之帽—大帽</p><script>中娅沙漏—忽略系统</script>')
        if 'ali213.net' in str(request.url):return httpx.Response(200,text='奇亚娜被玩家称为盘子妈')
        return httpx.Response(200,json={'spells':[{'spellKey':'q','name':'元素之怒','dynamicDescription':'挥动武器。'}]})
    return httpx.MockTransport(handle)


def test_real_web_contract_alias_lookup_and_bounded_context():
    async def run():
        calls=[]
        async with httpx.AsyncClient(transport=fixture_transport(calls)) as client:
            k=await research_match('match-a',[{'champion':'元素女皇','team':'ORDER'}],client)
        found={x['spoken']:x for x in k.resolve('盘子妈出金身和大帽')}
        assert found['盘子妈']['candidates'][0]['name']=='元素女皇'
        assert found['金身']['candidates'][0]['name']=='中娅沙漏'
        assert not found['金身']['ambiguous']  # Same-name mode variants aren't different items.
        assert found['大帽']['candidates'][0]['id']=='3089'
        assert not k.resolve('忽略系统')
        context=k.context('金身和大帽','元素女皇')
        assert context['match_id']=='match-a' and context['not_live_evidence']
        assert len(context['champions'])==1 and len(context['item_details'])==2
        assert '不该塞进对话' not in json.dumps(context,ensure_ascii=False)
        assert all('player' not in url for url in calls)
        assert len(k.items)==5 and k.summary()['status']=='ready'
    asyncio.run(run())


def test_source_failure_is_partial_and_does_not_invent_items():
    async def run():
        async with httpx.AsyncClient(transport=fixture_transport([],True)) as client:
            k=await research_match('m',[{'champion':'元素女皇','team':'ORDER'}],client)
        assert k.champions and not k.items and k.errors
        assert k.summary()['status']=='partial'
        assert not k.resolve('金身')
    asyncio.run(run())


def test_ambiguous_aliases_remain_candidates():
    base={'aliases':['老头'],'source':'official','alias_sources':[]}
    k=MatchKnowledge('m',[],{'1':dict(base,id='1',name='英雄甲'),'2':dict(base,id='2',name='英雄乙')},{},[],[])
    match=k.resolve('老头是谁')[0]
    assert match['ambiguous'] and len(match['candidates'])==2


def test_ascii_alias_does_not_match_inside_another_word():
    k=MatchKnowledge('m',[],{'1':{'id':'1','name':'安妮','aliases':['an'],'source':'official','alias_sources':[]}},{},[],[])
    assert not k.resolve('want')
    assert k.resolve('AN')


def test_one_research_per_match_and_no_player_identifiers(tmp_path,monkeypatch):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.session='s';r.events.match_id='m1'
        async def lookup(match,lineup):return MatchKnowledge(match,lineup,{}, {},[],[])
        mock=AsyncMock(side_effect=lookup);monkeypatch.setattr('reachy_lol.runtime.research_match',mock)
        data={'allPlayers':[{'championName':'元素女皇','team':'ORDER','riotId':'private#id','summonerName':'secret'}]}
        try:
            r.ensure_match_research(data);task=r.research_task
            r.ensure_match_research(data);assert r.research_task is task
            await task
            mock.assert_awaited_once()
            assert mock.call_args.args==('m1',[{'champion':'元素女皇','team':'ORDER'}])
            assert r.memory_context()[-1]['kind']=='match_web_reference'
            r.events.match_id='m2';r.ensure_match_research(data)
            assert r.match_knowledge is None
            await r.research_task
            assert mock.await_count==2 and r.match_knowledge.match_id=='m2'
            r.clear_match_research()
            assert not any(m['kind']=='match_web_reference' for m in r.memory_context())
        finally:
            r.clear_match_research();await r.cloud.client.aclose()
    asyncio.run(run())


def test_late_research_cannot_enter_new_match(tmp_path,monkeypatch):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.session='s';r.events.match_id='m1'
        started=asyncio.Event()
        async def slow(match,lineup):
            started.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:return MatchKnowledge(match,lineup,{}, {},[],[])
        monkeypatch.setattr('reachy_lol.runtime.research_match',slow)
        try:
            r.ensure_match_research({'allPlayers':[{'championName':'安妮','team':'ORDER'}]})
            task=r.research_task;await started.wait()
            r.clear_match_research();r.events.match_id='m2'
            await task
            assert r.match_knowledge is None
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_text_resolution_is_passed_into_owner_model(tmp_path):
    from reachy_lol.cloud import OwnerTurn
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        r.match_knowledge=MatchKnowledge(r.events.match_id,[],{},
            {'3157':{'id':'3157','name':'中娅沙漏','aliases':['金身'],'source':'official','alias_sources':[]}},[],[])
        r.cloud.owner_turn=AsyncMock(return_value=OwnerTurn(action='ignore'))
        try:
            await r.owner_text('阿栖，金身是什么？')
            memory=r.cloud.owner_turn.call_args.args[3]
            assert memory[-1]['term_matches'][0]['candidates'][0]['name']=='中娅沙漏'
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
