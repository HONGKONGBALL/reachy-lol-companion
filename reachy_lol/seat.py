"""Bounded head yaw calibration in the robot's fixed coordinate frame."""
import math
import numpy as np


def yaw_degrees(pose):
    pose=np.asarray(pose,dtype=float)
    if pose.shape!=(4,4) or not np.isfinite(pose).all():
        raise ValueError('机器人姿态无效')
    return math.degrees(math.atan2(pose[1,0],pose[0,0]))


def seat_target(pose, yaw):
    yaw=float(yaw)
    if not math.isfinite(yaw) or abs(yaw)>20:
        raise ValueError('座位方向只支持 -20 至 20 度')
    current=yaw_degrees(pose)
    if abs(current)>30:
        raise ValueError('当前头部偏转较大，请先在官方控制器恢复正常姿态')
    return _with_yaw(pose,current,yaw)


def _with_yaw(pose,current,yaw):
    delta=math.radians(yaw-current)
    c,s=math.cos(delta),math.sin(delta)
    result=np.asarray(pose,dtype=float).copy()
    result[:3,:3]=np.array([[c,-s,0],[s,c,0],[0,0,1]])@result[:3,:3]
    return result


def seat_steps(pose, yaw):
    """At 25 ms/step, yaw speed never exceeds 8 degrees/second."""
    seat_target(pose,yaw)  # validate before yielding any motor targets
    current=yaw_degrees(pose)
    count=max(1,math.ceil(abs(float(yaw)-current)/.2))
    for index in range(1,count+1):
        yield _with_yaw(pose,current,current+(float(yaw)-current)*index/count)
