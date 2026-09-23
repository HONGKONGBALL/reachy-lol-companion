"""Check live telemetry, including the desktop SDK 1.8 stale-ready field."""
from datetime import datetime, timezone
import math


def needs_live_probe(status):
    backend = status.get('backend_status') or {}
    return (status.get('version') == '1.8.0' and status.get('state') == 'running'
            and not backend.get('ready') and not status.get('error') and not backend.get('error'))


def robot_health(status, telemetry=None, now=None):
    backend = status.get('backend_status') or {}
    if status.get('error') or backend.get('error'):
        return False, str(status.get('error') or backend.get('error'))
    if status.get('simulation_enabled') or status.get('mockup_sim_enabled'):
        return False, '当前是模拟机器人'
    if not (status.get('no_media') is True or status.get('media_released') is True):
        return False, '请释放官方后台的摄像头和音频资源'
    if status.get('state') != 'running':
        return False, '机器人服务未运行'
    if backend.get('ready') is True:
        return True, '实机已连接 · 摄像头禁用'
    if needs_live_probe(status) and isinstance(telemetry, dict):
        try:
            stamp = datetime.fromisoformat(telemetry['timestamp'].replace('Z', '+00:00'))
            age = (now or datetime.now(timezone.utc)).timestamp() - stamp.timestamp()
            joints, antennas = telemetry['head_joints'], telemetry['antennas_position']
            valid = (len(joints) == 7 and len(antennas) == 2
                     and all(isinstance(v, (float, int)) and not isinstance(v, bool)
                             and math.isfinite(v) for v in joints + antennas))
            if valid and 0 <= age < 2:
                return True, '实机已连接 · 9 关节实时校验 · 摄像头禁用'
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
    return False, '电机数据尚未就绪或已过期'
