import asyncio
from unittest.mock import AsyncMock
from reachy_lol.runtime import Runtime
from reachy_lol.core import Candidate, Frame
from reachy_lol.cloud import Situation, Claim, Cloud
import pytest


@pytest.mark.parametrize('running', [False, True])
def test_motor_failure_preserves_error_and_only_stops_session_audio(tmp_path, monkeypatch, running):
    async def run():
        import httpx
        r=Runtime(tmp_path)
        r.gate.running=running
        r.audio.playing=True
        r.halt=AsyncMock()
        response=httpx.Response(200, json={
            'backend_status':None, 'no_media':True,
            'error':'No motors detected. Check power supply.'},
            request=httpx.Request('GET','http://127.0.0.1:8000/api/daemon/status'))
        client=AsyncMock()
        client.__aenter__.return_value=client
        client.get.return_value=response
        monkeypatch.setattr('reachy_lol.runtime.httpx.AsyncClient',lambda **kwargs:client)
        async def stop_after_one_poll(*args):
            raise asyncio.CancelledError()
        monkeypatch.setattr('reachy_lol.runtime.asyncio.sleep',stop_after_one_poll)
        with pytest.raises(asyncio.CancelledError):
            await r.robot_status_loop()
        assert 'No motors detected' in r.state['robot']
        assert r.halt.await_count == int(running)
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_end_clears_context_and_late_work(tmp_path):
    async def run():
        r=Runtime(tmp_path)
        r.gate.running=True
        r.audio.stop=lambda:None
        r.pending.append(Candidate('test','aqi',0,0))
        r.memory.append({'kind':'owner_statement','text':'private'})
        r.identities.friends={'private-player':'private-nickname'}
        r.buffer.add(Frame('f',1,b'123'))
        r.analysis.put_nowait((0,[],[],None))
        await r.control('end')
        assert not r.gate.running
        assert not r.memory and not r.buffer.frames and not r.pending
        assert r.analysis.empty() and r.latest is None
        assert not r.identities.friends and r.identities.match_id is None
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_start_with_failed_hardware_does_not_listen_or_upload(tmp_path):
    async def run():
        r=Runtime(tmp_path)
        r.capture.hwnd=123
        r.start_mic=lambda:pytest.fail('must not listen with failed preflight')
        with pytest.raises(ValueError,match='本体尚未就绪'):
            await r.control('start')
        assert not r.gate.running and r.session is None
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_unknown_evidence_is_rejected():
    async def run():
        c=Cloud(lambda x:None)
        c.structured=AsyncMock(return_value=Situation(
            observations=[Claim(text='test',evidence=['invented'])],inferences=[],unknowns=[],
            contribution='',outcome='',safe=False,meaningful=True))
        with pytest.raises(ValueError):
            await c.analyze([Frame('actual',1,b'123')],[],None)
        await c.client.aclose()
    asyncio.run(run())


def test_cancelled_tts_does_not_play(tmp_path):
    async def run():
        import time
        r=Runtime(tmp_path)
        r.audio.stop=lambda:None
        r.audio.play=lambda *a: pytest.fail('late audio was played')
        now=time.monotonic()
        r.gate.running=True
        r.gate.robot_ready=True
        r.gate.robot_at=now
        r.gate.safe_since=now-3
        r.gate.last_local=r.gate.visual_at=now
        r.gate.visual_safe=True
        began=asyncio.Event()
        release=asyncio.Event()
        async def late(*args):
            began.set()
            await release.wait()
            return b'late audio'
        r.cloud.tts=late
        r.pending.append(Candidate('test','aqi',r.gate.epoch,now))
        task=asyncio.create_task(r.speech_loop())
        await began.wait()
        await r.control('role','anao')
        release.set()
        await asyncio.sleep(.08)
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await r.cloud.client.aclose()
    asyncio.run(run())
