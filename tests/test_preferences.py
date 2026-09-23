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
