from datetime import datetime, timezone, timedelta
from reachy_lol.daemon_health import robot_health
import pytest
import asyncio
from unittest.mock import AsyncMock
import httpx
from reachy_lol.runtime import Runtime


def fixture():
    now=datetime.now(timezone.utc)
    status=dict(version='1.8.0',state='running',media_released=True,
                backend_status={'ready':False})
    telemetry=dict(timestamp=now.isoformat(),head_joints=[0.0]*7,antennas_position=[0.0]*2)
    return now,status,telemetry


def test_desktop_stale_ready_requires_live_nine_joint_telemetry():
    now,status,telemetry=fixture()
    assert robot_health(status,telemetry,now)[0]
    assert not robot_health(status,None,now)[0]
    telemetry['timestamp']=(now-timedelta(seconds=3)).isoformat()
    assert not robot_health(status,telemetry,now)[0]


@pytest.mark.parametrize('change', [
    {'error':'motor disconnected'}, {'simulation_enabled':True},
    {'media_released':False}, {'state':'stopped'}, {'version':'1.11.0'},
    {'backend_status':{'ready':False,'error':'motor failed'}}])
def test_telemetry_never_bypasses_other_health_checks(change):
    now,status,telemetry=fixture()
    status.update(change)
    assert not robot_health(status,telemetry,now)[0]


@pytest.mark.parametrize('joints', [[0]*6,[float('nan')]*7,[True]*7])
def test_bad_joint_data_rejected(joints):
    now,status,telemetry=fixture()
    telemetry['head_joints']=joints
    assert not robot_health(status,telemetry,now)[0]


@pytest.mark.parametrize('busy',[True,False])
def test_connect_releases_media_only_when_official_robot_is_free(tmp_path,monkeypatch,busy):
    async def run():
        r=Runtime(tmp_path)
        _,status,telemetry=fixture()
        status['media_released']=False
        released={**status,'media_released':True}
        def response(data):
            return httpx.Response(200,json=data,request=httpx.Request('GET','http://127.0.0.1:8000'))
        client=AsyncMock();client.__aenter__.return_value=client
        client.get.side_effect=[response(status),response({'state':'local_app' if busy else 'free'}),
                                response(released),response(telemetry)]
        client.post.return_value=response({'status':'ok'})
        monkeypatch.setattr('reachy_lol.runtime.httpx.AsyncClient',lambda **kw:client)
        if busy:
            with pytest.raises(ValueError,match='其他官方应用'):
                await r.control('connect')
            client.post.assert_not_awaited()
        else:
            await r.control('connect')
            client.post.assert_awaited_once_with('http://127.0.0.1:8000/api/media/release')
            assert r.gate.robot_ready
        assert not r.gate.running and r.mic_thread is None
        await r.cloud.client.aclose()
    asyncio.run(run())
