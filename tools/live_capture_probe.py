"""Local capture timing and pixel stability; no images are saved or uploaded."""
import json
import time
import uuid
from pathlib import Path
import numpy as np
from reachy_lol.capture import Capture, windows
from reachy_lol.core import Frame
from reachy_lol.visual_safety import pixels, stable


def main():
    c=Capture();selected=[w for w in windows() if w['is_game']]
    if len(selected)!=1: raise RuntimeError('Choose one game first')
    c.select(selected[0]['hwnd'])
    previous=anchor=None
    last=None
    rows=[]
    for _ in range(30):
        started=time.monotonic()
        jpeg=c.grab();at=time.monotonic()
        p=pixels(Frame(uuid.uuid4().hex,at,jpeg))
        row={'capture_ms':round((at-started)*1000),'gap_ms':round((at-last)*1000) if last else None}
        if anchor is None:anchor=p
        if previous is not None:
            diff=np.abs(p-previous).mean(axis=2)/255
            row.update(stable_previous=stable(previous,p),stable_anchor=stable(anchor,p),
                       mean=float(diff.mean()),changed=float((diff>.10).mean()),
                       max_cell=float(diff.reshape(9,6,12,8).mean(axis=(1,3)).max()),
                       hud=float(diff[40:52,30:70].mean()))
        rows.append(row);previous=p;last=at
        time.sleep(max(0,.5-(time.monotonic()-started)))
    result={'source':'actual_game_window','dimensions':[c.width,c.height],'samples':rows}
    Path('evidence/live-capture-metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
