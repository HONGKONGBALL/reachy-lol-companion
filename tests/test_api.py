from fastapi.testclient import TestClient
from reachy_lol.app import app, TOKEN


def test_control_rejects_external_origin_and_missing_token():
    c=TestClient(app)
    assert c.post('/api/control',json={'action':'stop'}).status_code==403
    assert c.post('/api/control',json={'action':'stop'},headers={
        'X-Demo-Token':TOKEN,'Origin':'https://other.example'}).status_code==403


def test_start_still_requires_a_ready_robot_without_a_game_window():
    c=TestClient(app)
    r=c.post('/api/control',json={'action':'start'},headers={'X-Demo-Token':TOKEN})
    assert r.status_code==400
    assert '本体尚未就绪' in r.json()['detail']


def test_preview_port_still_rejects_other_ports_and_external_origins(monkeypatch):
    monkeypatch.setattr('reachy_lol.app.PORT',8766)
    c=TestClient(app)
    headers={'X-Demo-Token':TOKEN,'Host':'127.0.0.1:8766','Origin':'http://127.0.0.1:8766'}
    assert c.get('/api/preferences',headers=headers).status_code==200
    assert c.get('/api/preferences',headers={**headers,'Host':'127.0.0.1:8765'}).status_code==403
    assert c.get('/api/preferences',headers={**headers,'Origin':'http://127.0.0.1:8765'}).status_code==403
