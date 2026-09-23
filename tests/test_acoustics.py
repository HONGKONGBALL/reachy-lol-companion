import asyncio
from unittest.mock import AsyncMock
import numpy as np
from reachy_lol.acoustics import PlaybackReference, SpeechFrontEnd, UtteranceSegmenter
from reachy_lol.runtime import Runtime


def test_reference_tracks_only_playback_and_expires():
    r=PlaybackReference()
    r.write(np.full((320,2),.1,dtype=np.float32),16000,at=10)
    assert np.allclose(r.read(10,320,16000),.1)
    assert not r.read(11,320,16000).any()
    assert not r.read(13,320,16000).any() and not r.blocks


def test_reference_preserves_queued_blocks_and_clear():
    r=PlaybackReference()
    r.write(np.full(320,.1,dtype=np.float32),16000,at=10)
    r.write(np.full(320,.2,dtype=np.float32),16000,at=10)
    assert np.allclose(r.read(10.02,320,16000),.2)
    r.clear()
    assert not r.read(10,640,16000).any()


def test_segment_preserves_first_frame_exactly_once():
    s=UtteranceSegmenter();starts=0
    for i in range(8):
        started,data,done=s.feed(np.full((320,1),i),True)
        starts+=started
    for i in range(30):
        _,data,done=s.feed(np.full((320,1),8+i),False)
    assert starts==1 and done
    assert data.shape==(38*320,1)
    assert np.array_equal(data[::320,0],np.arange(38))


def test_sparse_noise_does_not_accumulate_into_speech():
    s=UtteranceSegmenter()
    for i in range(200):
        started,data,done=s.feed(np.zeros((320,1)),i%4==0)
        assert not started and data is None


def test_dsp_silence_is_not_speech():
    f=SpeechFrontEnd(16000,PlaybackReference())
    for i in range(100):
        clean,speech,prob=f.process(np.zeros(320,dtype=np.float32),i*.02)
        assert np.isfinite(clean).all() and not speech


def test_new_voice_overlaps_asr_and_preserves_capture_order(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.gate.running=True
        old_started=asyncio.Event();release=asyncio.Event();new_finished=asyncio.Event()
        async def asr(wav):
            if wav==b'old':
                old_started.set()
                await release.wait()
                return 'old words'
            new_finished.set()
            return 'new words'
        r.cloud.asr=asr;r.owner_text=AsyncMock()
        old=asyncio.create_task(r.owner_audio(b'old',r.gate.epoch))
        await old_started.wait()
        epoch=await r.begin_owner_turn()
        new=asyncio.create_task(r.owner_audio(b'new',epoch))
        await asyncio.wait_for(new_finished.wait(),1)
        assert not old.done() and not r.owner_text.await_count
        release.set()
        await asyncio.wait_for(asyncio.gather(old,new),1)
        assert [call.args for call in r.owner_text.await_args_list]==[('old words',),('new words',)]
        assert r.owner_text.await_args.kwargs['turn_id']
        assert isinstance(r.owner_text.await_args.kwargs['input_finished_at'],float)
        assert r.owner_task is None
        assert not r.owner_tasks
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_stopped_session_does_not_upload_queued_audio(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.cloud.asr=AsyncMock()
        await r.owner_audio(b'private',r.gate.epoch)
        r.cloud.asr.assert_not_awaited()
        assert await r.begin_owner_turn() is None
        await r.cloud.client.aclose()
    asyncio.run(run())
