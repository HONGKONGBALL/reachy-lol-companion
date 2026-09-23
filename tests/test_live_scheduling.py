import asyncio
import io
import time
import base64
from unittest.mock import AsyncMock
from PIL import Image
import pytest
from reachy_lol.core import Frame
from reachy_lol.cloud import Situation,Cloud,SafetyCheck
from reachy_lol.runtime import Runtime


def jpeg():
    out=io.BytesIO();Image.new('RGB',(192,108),'gray').save(out,'JPEG');return out.getvalue()


def test_voice_onset_does_not_drop_a_game_frame(tmp_path,monkeypatch):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.cloud.configured=lambda _:False
        def grab():
            r.gate.invalidate('voice onset during capture')
            return jpeg()
        r.capture.grab=grab
        async def stop(_):raise asyncio.CancelledError()
        monkeypatch.setattr('reachy_lol.runtime.asyncio.sleep',stop)
        try:
            with pytest.raises(asyncio.CancelledError):await r.capture_loop()
            assert len(r.buffer.frames)==1
            assert r.capture_valid
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('corrected',[False,True])
def test_game_observations_survive_talk_but_not_a_correction(tmp_path,corrected):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        async def analyze(*args):
            r.gate.invalidate('a new utterance')
            if corrected:r.facts_revision+=1
            return Situation(observations=[],inferences=[],unknowns=[],contribution='',outcome='idle',
                             safe=False,meaningful=False)
        r.cloud.analyze=analyze
        r.analysis.put_nowait((r.gate.epoch,[Frame('a',time.monotonic(),jpeg())],[],None))
        task=asyncio.create_task(r.analysis_loop())
        try:
            async def settled():
                while not r.analysis.empty() or r.active_jobs:
                    await asyncio.sleep(.005)
            await asyncio.wait_for(settled(),1)
            assert (r.latest is None)==corrected
            assert not r.pending
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('changed_scene',[False,True,'new_match'])
def test_safety_survives_voice_but_not_a_changed_scene(tmp_path,changed_scene):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.capture_valid=True;r.capture.hwnd=42
        now=time.monotonic()
        for id,at in [('a',now-.7),('b',now-.1)]:
            r.buffer.add(Frame(id,at,jpeg(),window_id=42,segment=0))
        async def check(frames):
            r.gate.invalidate('new owner utterance')
            if changed_scene=='new_match':r.events.match_id='new match'
            elif changed_scene:r.capture_segment+=1
            return Situation(observations=[],inferences=[],unknowns=[],contribution='',outcome='',
                             safe=True,meaningful=False,safe_context='base_idle',safety_evidence=['a','b'])
        r.cloud.safety=check
        r.safety_analysis.put_nowait((r.session,r.capture_segment))
        task=asyncio.create_task(r.safety_loop())
        try:
            await asyncio.sleep(.03)
            assert r.gate.visual_safe is (not changed_scene)
            if not changed_scene:assert r.visual_safety.anchor is not None
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('failure',[False,True])
@pytest.mark.parametrize('newer_safety',[False,True])
def test_old_analysis_cannot_override_newer_scene_safety(tmp_path,failure,newer_safety):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.audio.playing=True;r.halt=AsyncMock()
        now=time.monotonic()
        async def analyze(*args):
            r.gate.visual_safe=True
            r.gate.visual_at=now if newer_safety else now-2
            if failure:raise TimeoutError('delayed analysis')
            return Situation(observations=[],inferences=[],unknowns=[],contribution='',outcome='',
                             safe=False,meaningful=False)
        r.cloud.analyze=analyze
        r.analysis.put_nowait((r.gate.epoch,[Frame('old',now-1,jpeg())],[],None))
        task=asyncio.create_task(r.analysis_loop())
        try:
            await asyncio.sleep(.03)
            assert r.gate.visual_safe is newer_safety
            assert r.halt.await_count==int(not failure and not newer_safety)
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('kind',['safety','analysis'])
def test_shutdown_cancels_worker_even_while_session_is_paused(tmp_path,kind):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True;r.capture_valid=True
        started=asyncio.Event()
        async def pending(*args):
            started.set()
            await asyncio.Event().wait()
        r.cloud.safety=pending;r.cloud.analyze=pending
        now=time.monotonic()
        fs=[Frame('a',now-.6,jpeg()),Frame('b',now,jpeg())]
        for f in fs:r.buffer.add(f)
        if kind=='safety':r.safety_analysis.put_nowait((r.session,r.capture_segment))
        else:r.analysis.put_nowait((r.gate.epoch,fs,[],None))
        task=asyncio.create_task(r.safety_loop() if kind=='safety' else r.analysis_loop())
        try:
            await asyncio.wait_for(started.wait(),1)
            r.gate.paused=True
            task.cancel()
            done,_=await asyncio.wait({task},timeout=.1)
            assert task in done
            assert task.cancelled()
        finally:
            r.gate.paused=False;task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await r.cloud.client.aclose()
    asyncio.run(run())


def test_safety_upload_is_bounded_without_changing_source_evidence():
    async def run():
        out=io.BytesIO();Image.new('RGB',(1600,900),'gray').save(out,'JPEG')
        source=out.getvalue()
        frames=[Frame('a',1,source),Frame('b',1.5,source)]
        cloud=Cloud(lambda _:None)
        async def structured(kind,system,content,schema):
            images=[part for part in content if part.get('type')=='image_url']
            assert len(images)==2
            for part in images:
                raw=base64.b64decode(part['image_url']['url'].split(',',1)[1])
                with Image.open(io.BytesIO(raw)) as im:
                    assert im.size==(512,288)
            return SafetyCheck(safe_context='base_idle',safety_evidence=['a','b'])
        cloud.structured=structured
        try:
            result=await cloud.safety(frames)
            assert result.safe and result.safety_evidence==['a','b']
            assert all(f.jpeg==source for f in frames)
        finally:await cloud.client.aclose()
    asyncio.run(run())
