import asyncio
import time
import numpy as np
import pytest
from reachy_lol.seat import seat_target,seat_steps,yaw_degrees
from reachy_lol.runtime import Runtime
from reachy_lol.hardware import Robot


def test_seat_trajectory_is_bounded_and_does_not_move_translation():
    pose=np.eye(4);pose[:3,3]=[.01,-.01,.02]
    steps=list(seat_steps(pose,20))
    angles=[0]+[yaw_degrees(p) for p in steps]
    assert np.max(np.abs(np.diff(angles)))<=.200001
    assert angles[-1]==pytest.approx(20)
    assert all(np.allclose(p[:3,3],pose[:3,3]) for p in steps)
    assert all(np.allclose(p[:3,:3].T@p[:3,:3],np.eye(3)) for p in steps)
    with pytest.raises(ValueError): list(seat_steps(pose,float('nan')))
    with pytest.raises(ValueError): list(seat_steps(pose,21))
    # Applying an absolute yaw twice must not accumulate rotation.
    assert yaw_degrees(seat_target(seat_target(pose,15),15))==pytest.approx(15)


def test_cancelled_seat_adjustment_not_persisted(tmp_path):
    async def run():
        r=Runtime(tmp_path);r.audio.stop=lambda:None
        r.robot.face_seat=lambda *args:{'cancelled':True}
        with pytest.raises(ValueError,match='未保存'):
            await r.configure_seat(10)
        assert r.preferences.seat_yaw is None
        assert not (tmp_path/'preferences.json').exists()
        await r.cloud.client.aclose()
    asyncio.run(run())


def test_seat_feedback_handles_tracking_error_with_bounded_commands(monkeypatch):
    class Mini:
        pose=np.eye(4)
        commands=[]
        def get_current_head_pose(self): return self.pose.copy()
        def get_current_joint_positions(self): return [],[0,0]
        def set_target(self,head):
            angle=yaw_degrees(head)
            self.commands.append(angle)
            self.pose=seat_target(np.eye(4),angle-3)
    robot=Robot();robot.mini=Mini();robot.connect=lambda:None
    monkeypatch.setattr('reachy_lol.hardware.time.sleep',lambda _:None)
    result=robot.face_seat(5)
    assert not result['cancelled'] and abs(result['yaw_degrees']-5)<1
    assert np.max(np.abs(np.diff([0]+robot.mini.commands)))<=.200001
    assert max(robot.mini.commands)<=9


def test_clear_waits_for_cancelled_request_and_discards_late_usage(tmp_path):
    async def run():
        evidence=tmp_path/'evidence';evidence.mkdir()
        for name in ('usage.jsonl','decisions.jsonl','hardware.jsonl','independent-report.json'):
            (evidence/name).write_text('test',encoding='utf8')
        r=Runtime(tmp_path);r.audio.stop=lambda:None;r.gate.running=True
        r.memory.append({'kind':'owner_statement','text':'private'})
        old=time.monotonic()
        finished=asyncio.Event()
        async def request():
            try: await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.01)
                r.usage({'started_monotonic':old,'status':'cancelled'})
                finished.set()
        task=asyncio.create_task(r.job(request()))
        await asyncio.sleep(0);await asyncio.sleep(0)
        result=await r.clear_local_data()
        await asyncio.gather(task,return_exceptions=True)
        assert finished.is_set() and result['cleared']
        assert not r.memory and not r.usages and not r.gate.running
        assert not (evidence/'usage.jsonl').exists()
        assert not (evidence/'decisions.jsonl').exists()
        assert (evidence/'independent-report.json').exists()
        r.usage({'started_monotonic':old,'status':'late'})
        assert not (evidence/'usage.jsonl').exists()
        await r.cloud.client.aclose()
    asyncio.run(run())
