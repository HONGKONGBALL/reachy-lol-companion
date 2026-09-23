import asyncio
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from reachy_lol.cloud import Cloud, OwnerTurn, Reply
from reachy_lol.conversation import reply_problem
from reachy_lol.long_memory import LongMemory, utcnow
from reachy_lol.opgg import decode_data, champion_build
from reachy_lol.runtime import Runtime
from reachy_lol.companion_motions import CompanionMotions
from reachy_skills.community import CommunityLibrary


def test_opgg_data_not_executable():
    data=decode_data('class Build: ids,name\n\nBuild([3157],"金身")')
    assert data=={'ids':[3157],'name':'金身'}
    with pytest.raises(ValueError):decode_data('__import__("os").system("echo bad")')
    with pytest.raises(ValueError):decode_data('class A: x\nA(1,2)')


def test_opgg_http_contract_and_no_private_headers():
    async def run():
        calls=[]
        def handle(request):
            assert 'authorization' not in request.headers
            body=json.loads(request.content);calls.append(body)
            if body['method']=='initialize':
                return httpx.Response(200,json={'result':{'protocolVersion':'2025-06-18'}},headers={'mcp-session-id':'test'})
            assert request.headers['mcp-session-id']=='test'
            if body['method']=='notifications/initialized':return httpx.Response(202)
            return httpx.Response(200,json={'result':{'content':[{'type':'text','text':json.dumps({
                'champion':'元素女皇','position':'MID','data':{'core_items':{'ids':[6698]},'trends':{'win':{'version':'16.19'}}}})}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            build=await champion_build('Qiyana',client=client)
        assert build['patch']=='16.19' and build['position_inferred']
        assert calls[-1]['params']['arguments']['champion']=='QIYANA'
    asyncio.run(run())


def test_equipment_survives_restart_and_session_clear(tmp_path):
    async def run():
        memory=LongMemory(tmp_path)
        memory.data['items']={'3157':{'id':'3157','name':'中娅沙漏','aliases':['金身'],
                                     'description':'进入凝滞状态','source':'official','alias_sources':[]}}
        memory.data['fetched_at']=utcnow();memory.save()
        r=Runtime(tmp_path)
        r.audio.stop=lambda:None
        try:
            assert r.memory_context('金身')[0]['item_details'][0]['description']=='进入凝滞状态'
            await r.control('end')
            assert r.memory_context('金身')[0]['kind']=='local_equipment_memory'
            assert LongMemory(tmp_path).data['items']['3157']['aliases']==['金身']
            assert not r.memory_context('无关话题')[0]['item_details']
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_build_prefetched_and_late_result_discarded(tmp_path,monkeypatch):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.session='s';r.events.match_id='m'
        r.identity={'champion':'奇亚娜'}
        r.long_memory.data['champions']={'246':{'key':'Qiyana','aliases':['奇亚娜']}}
        started=asyncio.Event()
        async def lookup(*args):
            started.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                return {'champion':'奇亚娜','position':'MID','patch':'16.19','data':{}}
        mock=AsyncMock(side_effect=lookup)
        monkeypatch.setattr('reachy_lol.runtime.champion_build',mock)
        try:
            r.ensure_build_research();task=r.build_task
            r.ensure_build_research();assert r.build_task is task
            await started.wait()
            r.clear_match_research();r.events.match_id='next'
            await task
            assert r.build_knowledge is None
            mock.assert_awaited_once_with('Qiyana','all')
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_empathy_rewrite_keeps_knowledge_and_hf_motion():
    async def run():
        c=Cloud(lambda _:None)
        bad='队友确实没跟上，但是是不是死人还不能确定。'
        assert reply_problem(bad,[],'队友是死人吗')=='invalidating_owner_emotion'
        assert reply_problem('不能确定他是否已死亡。',[],'你能确认他真的死了吗') is None
        memory=[{'kind':'local_equipment_memory','item_details':[{'name':'金身'}]}]
        c.structured=AsyncMock(side_effect=[OwnerTurn(action='respond',reply=Reply(text=bad,motion='neutral',evidence=[])),
            Reply(text='等半天没人接应，真让人窝火。',motion='anne.no_way',evidence=[])])
        try:
            turn=await c.owner_turn('aqi','队友是死人吗',None,memory,{}, {})
            assert turn.reply.motion=='anne.no_way'
            assert json.loads(c.structured.call_args.args[2])['memory']==memory
        finally:await c.client.aclose()
    asyncio.run(run())


def test_hf_playback_reuses_controller_and_mutes_audio():
    async def run():
        robot=type('Robot',(),{})()
        robot.async_play_move=AsyncMock();robot.cancel_move=lambda:None
        motions=CompanionMotions();motions.loop=asyncio.get_running_loop()
        motions.library=CommunityLibrary({'stella.think':object()})
        first=await motions.play(robot,'stella.think',lambda:True)
        controller=motions.controller
        second=await motions.play(robot,'stella.think',lambda:True)
        assert first['status']==second['status']=='completed'
        assert motions.controller is controller
        assert robot.async_play_move.call_args.kwargs['sound'] is False
        result=await motions.play(robot,'stella.think',lambda:False)
        assert result['status']=='stopped' and robot.async_play_move.await_count==2
    asyncio.run(run())


def test_inferred_lane_prefetches_alternative_without_invalid_all_request():
    async def run():
        lanes=[]
        def handle(request):
            body=json.loads(request.content)
            if body['method']=='initialize':return httpx.Response(200,json={'result':{}})
            if body['method']=='notifications/initialized':return httpx.Response(202)
            lane=body['params']['arguments']['position'];lanes.append(lane)
            assert lane!='all'
            data={'champion':'元素女皇','position':lane.upper(),'data':{'core_items':{'ids':[6698 if lane=='mid' else 6699]},
                  'summary':{'positions':[{'name':'JUNGLE','stats':{'play':200}},{'name':'MID','stats':{'play':100}}]}}}
            return httpx.Response(200,json={'result':{'structuredContent':data}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            build=await champion_build('Qiyana',client=client)
        assert lanes==['mid','jungle']
        assert build['position']=='JUNGLE'
        assert build['alternatives'][0]['position']=='MID'
        assert build['alternatives'][0]['data']['core_items']['ids']==[6698]
    asyncio.run(run())


def test_offline_refresh_preserves_persistent_items(tmp_path,monkeypatch):
    from reachy_lol.match_research import MatchKnowledge
    async def run():
        memory=LongMemory(tmp_path)
        memory.data['items']={'3157':{'id':'3157','name':'中娅沙漏','aliases':['金身'],'source':'official','alias_sources':[]}}
        memory.save()
        monkeypatch.setattr('reachy_lol.long_memory.research_match',AsyncMock(return_value=MatchKnowledge('x',[],{},{},[],['offline'])))
        await memory.refresh()
        assert memory.data['items']==LongMemory(tmp_path).data['items']
        assert memory.context('金身')['stale'] and memory.error
    asyncio.run(run())
