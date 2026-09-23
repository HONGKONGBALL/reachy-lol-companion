import asyncio
import io
import time
import pytest
from PIL import Image
from reachy_lol.cloud import Situation
from reachy_lol.core import Frame, Events
from reachy_lol.visual_safety import VisualSafety
from reachy_lol.runtime import Runtime
from reachy_lol.capture import Capture


def frame(id, at, color='gray',segment=1):
    output=io.BytesIO();Image.new('RGB',(192,108),color).save(output,'JPEG')
    return Frame(id,at,output.getvalue(),window_id=42,segment=segment)


def safe():
    return Situation(observations=[],inferences=[],unknowns=[],contribution='',outcome='',
                     safe=True,meaningful=False,safe_context='base_idle',safety_evidence=['a','b'])


def test_fallback_requires_two_supported_frames_and_local_stability():
    s=VisualSafety();frames=[frame('a',10),frame('b',11)]
    r=safe();r.safety_evidence=['b']
    assert not s.accept(r,frames)
    assert s.accept(safe(),frames)
    assert s.observe(frame('c',12))
    assert not s.observe(frame('d',12.5,'red'))
    assert not s.observe(frame('e',13)) # does not automatically regain trust


@pytest.mark.parametrize('change',[{'safe':False},{'safe_context':'unknown'},
    {'safe_context':'risk'},{'safety_evidence':['a','invented']}])
def test_unknown_risk_or_invalid_evidence_never_allows_fallback(change):
    r=safe().model_copy(update=change)
    assert not VisualSafety().accept(r,[frame('a',10),frame('b',11)])


def test_expiry_and_scene_boundaries():
    s=VisualSafety();fs=[frame('a',10),frame('b',11)]
    assert s.accept(safe(),fs)
    assert not s.observe(frame('c',17.1))
    assert s.accept(safe(),fs)
    assert not s.observe(frame('c',12,segment=2))
    assert not s.accept(safe(),[frame('a',1),frame('b',11)])


def test_slow_model_requires_all_intervening_frames_and_fixed_source_expiry():
    s=VisualSafety();fs=[frame('a',10),frame('b',11)]
    assert s.accept(safe(),fs)
    captured=[frame(str(t),t) for t in range(12,20)]
    assert s.revalidate(captured,19.1)
    assert s.source_at==11 and s.verified_at==19
    assert s.accept(safe(),fs)
    assert not s.revalidate(captured[1:],19.1) # gap at the start cannot be hidden
    assert s.accept(safe(),fs)
    captured[3]=frame('changed',15,'red')
    assert not s.revalidate(captured,19.1)
    assert s.accept(safe(),fs)
    assert s.revalidate([frame(str(t),t) for t in range(12,32)],31)
    assert not s.observe(frame('expired',31.5))


@pytest.mark.parametrize('live_low_health',[False,True])
def test_runtime_visual_fallback_never_overrides_low_api_health(tmp_path,monkeypatch,live_low_health):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        now=time.monotonic()
        fs=[frame('a',now-1),frame('b',now-.5)]
        assert r.visual_safety.accept(safe(),fs)
        r.capture.hwnd=42;r.capture_segment=1;r.capture.change=0
        r.capture.grab=lambda:fs[-1].jpeg
        r.cloud.configured=lambda kind:False
        if live_low_health:
            r.game={'activePlayer':{'championStats':{'currentHealth':10,'maxHealth':100}}}
            r.game_at=now;r.health=10
        async def finish(*args): raise asyncio.CancelledError()
        monkeypatch.setattr('reachy_lol.runtime.asyncio.sleep',finish)
        with pytest.raises(asyncio.CancelledError): await r.capture_loop()
        assert (r.gate.safe_since is not None)==(not live_low_health)
        assert r.identity is None
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_lobby_cannot_be_selected_for_game_capture(monkeypatch):
    monkeypatch.setattr('reachy_lol.capture.windows',lambda:[{'hwnd':42,'title':'League of Legends','is_game':False}])
    with pytest.raises(ValueError,match='大厅'): Capture().select(42)


@pytest.mark.parametrize('raw,expected',[('false',False),('TRUE',True),('unknown',None),(1,None)])
def test_event_adapter_normalizes_stolen_without_truthiness(raw,expected):
    e=Events();e.ingest({'gameData':{'gameTime':10},'events':{'Events':[]}})
    events,_=e.ingest({'gameData':{'gameTime':11},'events':{'Events':[
        {'EventID':1,'EventTime':11,'EventName':'DragonKill','Stolen':raw}]}})
    assert events[0]['Stolen'] is expected
