import asyncio
import pytest
from reachy_lol import hardware
from reachy_lol.runtime import Runtime
from reachy_lol.settings import Preferences


def test_device_selection_survives_index_change_and_rejects_missing(monkeypatch):
    device={'id':24,'name':'Reachy Mini Audio','host':'WASAPI',
            'key':'WASAPI::Reachy Mini Audio','inputs':2,'outputs':0}
    monkeypatch.setattr(hardware,'audio_devices',lambda:[device.copy()])
    assert hardware.choose_device('input',device['key'])['id']==24
    device['id']=31
    assert hardware.choose_device('input',device['key'])['id']==31
    with pytest.raises(ValueError,match='离线'):
        hardware.choose_device('output',device['key'])
    with pytest.raises(ValueError,match='离线'):
        hardware.choose_device('input','WASAPI::PC microphone')


def test_device_changes_blocked_during_session_and_volume_restored(tmp_path,monkeypatch):
    async def run():
        r=Runtime(tmp_path)
        r.audio.stop=lambda:None
        r.gate.running=True
        with pytest.raises(ValueError,match='结束陪玩'):
            await r.save_preferences(Preferences(input_device='WASAPI::Reachy Mini Audio'))
        assert r.audio.input_device is None
        r.gate.running=False
        monkeypatch.setattr(hardware,'audio_devices',lambda:[
            {'id':31,'key':'WASAPI::Reachy Mini Audio','inputs':2,'outputs':2,'host':'WASAPI'}])
        prefs=Preferences(volume=.2,input_device='WASAPI::Reachy Mini Audio',output_device='WASAPI::Reachy Mini Audio')
        await r.save_preferences(prefs)
        restored=Runtime(tmp_path)
        assert restored.audio.volume==.2
        assert restored.audio.input_device==prefs.input_device
        assert restored.audio.output_device==prefs.output_device
        await r.cloud.client.aclose()
        await restored.cloud.client.aclose()
    asyncio.run(run())
