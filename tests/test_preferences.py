import asyncio
import pytest
from reachy_lol.runtime import Runtime
from reachy_lol.settings import Preferences, EventPreference
from reachy_lol.core import Candidate

def test_settings_save_persists_and_cancels_old_voice(tmp_path):
    async def run():
        r=Runtime(tmp_path)
        r.audio.stop=lambda:None
        r.pending.append(Candidate('old','aqi',r.gate.epoch,0))
        epoch=r.gate.epoch
        await r.save_preferences(Preferences(name='搭子',voice='breeze',intensity='chill'))
        assert r.gate.epoch>epoch and not r.pending
        assert r.role=='anao' and r.gate.cooldown==45
        restored=Runtime(tmp_path)
        assert restored.preferences.name=='搭子'
        assert restored.preferences.voice=='breeze'
        assert restored.gate.cooldown==45
        await r.cloud.client.aclose()
        await restored.cloud.client.aclose()
    asyncio.run(run())

def test_event_preference_filters_triggers(tmp_path):
    async def run():
        r=Runtime(tmp_path)
        r.identity={'name':'owner'}
        r.preferences.events['death']=EventPreference(enabled=False)
        r.preferences.events['objective']=EventPreference(reaction='Silent')
        events=[{'EventName':'ChampionKill','VictimName':'owner'},
                {'EventName':'DragonKill'}, {'EventName':'Multikill'}]
        assert r.relevant_events(events)==[events[2]]
        await r.cloud.client.aclose()
    asyncio.run(run())

def test_missing_voice_never_falls_back_to_browser_or_other_voice(tmp_path,monkeypatch):
    async def run():
        monkeypatch.delenv('VOICE_VELVET',raising=False)
        r=Runtime(tmp_path)
        r.audio.play=lambda *args:pytest.fail('Unexpected playback')
        with pytest.raises(ValueError,match='尚未配置'):
            await r.audition('velvet')
        await r.cloud.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('mode,cooldown',[('chill',45),('normal',30),('chaos',8)])
def test_live_intensity_endpoint_applies_persists_and_unmutes(tmp_path,monkeypatch,mode,cooldown):
    from fastapi.testclient import TestClient
    import importlib
    module=importlib.import_module('reachy_lol.app')
    r=Runtime(tmp_path);r.gate.running=True;r.gate.quiet=True
    r.preferences.intensity=mode  # Reselecting the existing card must work too.
    r.preferences.name='搭子';r.audio.stop=lambda:None
    monkeypatch.setattr(module,'runtime',r)
    try:
        client=TestClient(module.app)
        response=client.put('/api/intensity',json={'intensity':mode},headers={'X-Demo-Token':module.TOKEN})
        assert response.status_code==200
        assert response.json()['behavior']=={'intensity':mode,'quiet':False,'cooldown':cooldown}
        assert r.gate.running and not r.gate.quiet
        assert r.gate.relaxed is (mode=='chaos')
        assert r.preferences.name=='搭子'
        restored=Runtime(tmp_path)
        try:
            assert restored.preferences.intensity==mode and restored.gate.cooldown==cooldown
        finally:asyncio.run(restored.cloud.client.aclose())
        assert client.put('/api/intensity',json={'intensity':'invalid'},headers={'X-Demo-Token':module.TOKEN}).status_code==422
        assert client.put('/api/intensity',json={'intensity':'normal'}).status_code==403
    finally:asyncio.run(r.cloud.client.aclose())


def test_failed_intensity_save_keeps_running_mode_and_mute(tmp_path,monkeypatch):
    from pathlib import Path
    async def run():
        r=Runtime(tmp_path);r.gate.quiet=True
        previous=r.preferences.intensity
        def fail(*args,**kwargs):raise OSError('disk full')
        monkeypatch.setattr(Path,'write_text',fail)
        try:
            with pytest.raises(OSError):await r.set_intensity('chaos')
            assert r.preferences.intensity==previous and r.gate.quiet
        finally:await r.cloud.client.aclose()
    asyncio.run(run())


def test_saving_other_settings_does_not_cancel_explicit_quiet(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.quiet=True
        try:
            await r.save_preferences(r.preferences.model_copy(update={'volume':.5}))
            assert r.gate.quiet
            await r.save_preferences(r.preferences.model_copy(update={'intensity':'chaos'}))
            assert not r.gate.quiet
        finally:await r.cloud.client.aclose()
    asyncio.run(run())
