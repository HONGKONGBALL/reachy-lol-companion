import pytest
from reachy_lol.identity import Identity


def packet(active='me#CN', champion='Ahri'):
    return {'activePlayer':{'riotId':active},'allPlayers':[
        {'riotId':'me#CN','summonerName':'old-me','championName':champion,'team':'ORDER'},
        {'riotId':'friend#CN','summonerName':'old-friend','championName':'Lee Sin','team':'ORDER'},
        {'riotId':'enemy#CN','championName':'Garen','team':'CHAOS'}]}


def test_auto_identity_and_party_is_never_inferred():
    i=Identity()
    owner=i.update(packet(),'m1')
    assert owner['champion']=='Ahri' and owner['source']=='live_client'
    assert owner['friends']==[]
    assert 'old-me' in owner['aliases']


def test_confirmation_survives_poll_and_disconnect_but_not_new_match():
    i=Identity()
    i.update(packet(active='unknown'),'m1')
    assert i.owner is None
    i.confirm('m1','old-me',[{'name':'friend#CN','nickname':'小李'}])
    assert i.update(packet(active='unknown'),'m1')['source']=='owner_confirmed'
    i.disconnect()
    assert i.context() is None and i.snapshot()['roster']==[]
    with pytest.raises(ValueError):
        i.confirm('m1','me#CN',[])
    assert i.update(packet(active='unknown'),'m1')['friends'][0]['nickname']=='小李'
    assert i.update(packet(active='unknown'),'m2') is None
    owner=i.update(packet(champion='Lux'),'m2')
    assert owner['source']=='live_client' and owner['champion']=='Lux'
    assert owner['friends'][0]['nickname']=='小李'


def test_stale_form_and_enemy_friend_rejected_without_mutation():
    i=Identity()
    i.update(packet(),'m2')
    before=i.snapshot()
    with pytest.raises(ValueError):
        i.confirm('m1','me#CN',[])
    with pytest.raises(ValueError):
        i.confirm('m2','me#CN',[{'name':'enemy#CN','nickname':'fake'}])
    assert i.snapshot()==before


def test_ambiguous_alias_is_unknown_and_snapshot_is_detached():
    i=Identity()
    data=packet(active='old-me')
    data['allPlayers'][1]['summonerName']='old-me'
    assert i.update(data,'m1') is None
    with pytest.raises(ValueError):
        i.confirm('m1','old-me',[])
    state=i.snapshot()
    state['roster'].clear()
    assert len(i.roster)==3


def test_explicit_unfriend_and_new_session_clear():
    i=Identity()
    i.update(packet(),'m1')
    i.confirm('m1','me#CN',[{'name':'friend#CN','nickname':'小李'}])
    i.confirm('m1','me#CN',[])
    assert not i.context()['friends']
    assert not Identity().friends


def test_cn_bare_event_name_matches_tagged_owner_only_when_unique():
    i=Identity();data=packet()
    assert 'me' in i.update(data,'m1')['aliases']
    data['allPlayers'][1]['riotId']='me#OTHER'
    assert 'me' not in i.update(data,'m1')['aliases']
    assert i.context()['name']=='me#CN'
