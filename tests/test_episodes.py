from reachy_lol.core import Frame
from reachy_lol.episodes import Episodes


def frame(i,at,segment=0):
    return Frame(str(i),at,b'1234',at,100,segment,1920,1080)


def situation(link=None,basis=(),meaningful=True,**kwargs):
    return dict(observations=[{'text':'入口交战','evidence':['1']}],inferences=[],
                unknowns=[],contribution='争取空间',outcome='尚未结束',meaningful=meaningful,
                continuation_of=link,continuity_evidence=list(basis),**kwargs)


def test_kill_multikill_and_objective_merge_with_two_sided_evidence():
    e=Episodes()
    f1,f2,f3=frame(1,1),frame(2,4),frame(3,7)
    first=e.record('m1',[f1],[f1],[{'event_key':'kill'}],situation())
    second=e.record('m1',[f2],[f1,f2],[{'event_key':'multi'}],situation(first.id,['1','2']))
    third=e.record('m1',[f3],[f1,f2,f3],[{'event_key':'dragon'}],situation(first.id,['2','3'],process_ended=True))
    assert first.id==second.id==third.id and len(e.items)==1
    assert {x['event_key'] for x in third.events}=={'kill','multi','dragon'}
    assert third.ended and third.revision==3


def test_clock_or_model_id_alone_is_not_a_merge():
    e=Episodes()
    first=e.record('m1',[frame(1,1)],[frame(1,1)],[],situation())
    second=e.record('m1',[frame(2,2)],[frame(2,2)],[],situation(first.id,['2']))
    assert first.id!=second.id and first.ended


def test_no_event_process_and_once_spoken_remains_spoken_after_updates():
    e=Episodes()
    first=e.record('m1',[frame(1,1)],[frame(1,1)],[],situation())
    revision=first.revision
    e.mark_spoken(first.id)
    assert not e.valid(first.id,revision)
    assert e.valid(first.id,revision,allow_spoken=True)
    later=e.record('m1',[frame(2,4)],[frame(1,1),frame(2,4)],[],situation(first.id,['1','2']))
    assert later.id==first.id and later.spoken and later.revision==revision
    assert not e.valid(later.id,later.revision)


def test_superseded_candidate_is_invalid_before_tts_completes():
    e=Episodes()
    first=e.record('m1',[frame(1,1)],[frame(1,1)],[],situation())
    revision=first.revision
    e.record('m1',[frame(2,4)],[frame(1,1),frame(2,4)],[],
             situation(first.id,['1','2'],supersedes_previous=True))
    assert not e.valid(first.id,revision)


def test_scene_gap_or_new_match_releases_media_but_keeps_summary():
    for match,source in [('m2',frame(2,4)),('m1',frame(2,4,1)),('m1',frame(2,20))]:
        e=Episodes()
        first=e.record('m1',[frame(1,1)],[frame(1,1)],[],situation())
        frames,context=e.prepare(match,[source])
        assert context is None and frames==[source] and first.frames==[]
        assert e.summaries()[0]['match_id']=='m1'


def test_keyframes_and_summaries_have_hard_bounds_and_end_clears():
    e=Episodes(max_summaries=3,max_frames=3,max_bytes=8)
    for i in range(10):
        e.record('m1',[frame(i,i)],[frame(x,x) for x in range(i+1)],[],situation())
    assert len(e.items)==3
    assert sum(len(f.jpeg) for item in e.items for f in item.frames)<=8
    e.clear()
    assert e.active is None and e.summaries()==[]


def test_correction_erases_claims_and_cannot_reenter_context():
    e=Episodes()
    first=e.record('m1',[frame(1,1)],[frame(1,1)],[],situation())
    e.revoke(first.id)
    summary=e.summaries()[0]
    assert summary['revoked'] and not summary['observed_fact'] and not summary['inference']
    assert not e.valid(first.id,first.revision)
    assert e.prepare('m1',[frame(2,4)])[1] is None


def test_ordinary_idle_snapshots_do_not_evict_important_memories():
    e=Episodes()
    first=e.record('m1',[frame(1,1)],[frame(1,1)],[],situation())
    for i in range(2,30):
        assert e.record('m1',[frame(i,i)],[frame(i,i)],[],situation(meaningful=False)) is None
    assert [x['episode_id'] for x in e.summaries()]==[first.id]
