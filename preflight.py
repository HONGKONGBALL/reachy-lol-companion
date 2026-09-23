"""Read-only Windows preflight; never opens camera or records audio."""
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import httpx
from dotenv import load_dotenv
from reachy_lol.capture import windows
from reachy_lol.hardware import audio_devices
from serial.tools.list_ports import comports
from reachy_lol.model_config import CONFIG_KEYS, KINDS, model_config

root=Path(__file__).resolve().parent
load_dotenv(root/'.env')
result={'platform':platform.platform(),'python':platform.python_version(),
        'versions':{n:importlib.metadata.version(n) for n in ('reachy-mini','sounddevice','fastapi','httpx')},
        'audio_devices':audio_devices(),'serial_ports':[{'device':p.device,'description':p.description,
                                                       'vid':p.vid,'pid':p.pid} for p in comports()],
        'game_windows':windows(),
        'config_presence':{k:bool(os.getenv(k)) for k in CONFIG_KEYS},
        'cloud_configured':{kind:model_config(kind).configured for kind in KINDS},
        'camera_opened':False,'evidence_type':'read_only_probe'}
with httpx.Client(timeout=2,verify=False,trust_env=False) as c:
    for label,url in [('robot','http://127.0.0.1:8000/api/daemon/status'),
                      ('live_client','https://127.0.0.1:2999/liveclientdata/gamestats')]:
        try:
            r=c.get(url)
            result[label]={'http_status':r.status_code,'payload':r.json() if r.status_code==200 else None}
        except Exception as exc:
            result[label]={'error':type(exc).__name__}
text=json.dumps(result,ensure_ascii=False,indent=2)
(root/'evidence'/'preflight.json').write_text(text,encoding='utf8')
print(text)
