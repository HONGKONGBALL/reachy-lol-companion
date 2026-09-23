from reachy_lol.core import Gate, Frame, FrameBuffer, Events, Candidate, boolean


def ready_gate():
    g=Gate(running=True,visual_safe=True,visual_at=10,robot_ready=True,robot_at=10)
    for t in (8,8.5,9,9.5,10):
        g.observe(t,True)
    return g


def test_gate_needs_continuous_fresh_local_and_visual_evidence():
    g=ready_gate()
    assert g.allowed(10)
    assert not g.allowed(11.3)
    g.observe(12,False)
    g.observe(13,True)
    assert not g.allowed(13)
    g.visual_at=4
    assert not g.allowed(10)


def test_quiet_speech_pause_and_cooldown():
    g=ready_gate()
    g.quiet=True
    assert not g.allowed(10)
    assert g.allowed(10,False)
    g.owner_speaking=True
    assert g.allowed(10,False)
    assert not g.allowed(10,True)
    g.owner_speaking=False
    g.paused=True
    assert not g.allowed(10,False)
    g.paused=g.quiet=False
    g.last_spoken=0
    assert not g.allowed(10)
    assert g.allowed(10,False)


def test_disconnected_or_stale_robot_blocks_owner_and_proactive_output():
    g=ready_gate()
    g.robot_ready=False
    assert not g.allowed(10,False) and not g.allowed(10,True)
    g.robot_ready=True
    g.robot_at=4
    assert not g.allowed(10,False)


def test_continuous_local_visual_checks_do_not_rewrite_source_time():
    g=ready_gate();g.visual_at=1
    assert not g.allowed(10,False)
    g.visual_continuity_at=10
    assert g.allowed(10,False)
    assert g.visual_at==1
    g.visual_continuity_at=8
    assert not g.allowed(10,False)
    g.visual_continuity_at=g.last_local=g.robot_at=22
    assert not g.allowed(22,False)


def test_cancelled_role_and_late_tts_never_valid():
    g=ready_gate()
    c=Candidate('你好','aqi',g.epoch,10)
    assert c.valid(g,'aqi',11)
    assert not c.valid(g,'anao',11)
    assert not c.valid(g,'aqi',31)
    g.invalidate('停止')
    assert not c.valid(g,'aqi',11)


def test_buffer_time_and_byte_limits():
    b=FrameBuffer(seconds=20,max_bytes=10)
    b.add(Frame('1',0,b'123456'))
    b.add(Frame('2',1,b'abcdef'))
    assert [f.id for f in b.frames]==['2']
    assert b.sample(22)==[]


def packet(t,events):
    return {'gameData':{'gameTime':t},'events':{'Events':events}}


def event(i,t):
    return {'EventID':i,'EventName':'ChampionKill','EventTime':t}


def test_reconnect_and_restart_do_not_replay_history():
    e=Events()
    old=event(1,1)
    new=event(2,11)
    assert e.ingest(packet(10,[old]))[0]==[]
    assert len(e.ingest(packet(11,[old,new]))[0])==1
    assert e.ingest(packet(12,[old,new]))[0]==[]
    e.connected=False
    assert e.ingest(packet(13,[old,new,event(3,13)]))[0]==[]
    match=e.match_id
    assert e.ingest(packet(0,[]))[1]
    assert e.match_id!=match


def test_unknown_and_string_booleans():
    assert boolean('false') is False
    assert boolean('TRUE') is True
    assert boolean(None) is None
    assert boolean('unknown') is None
