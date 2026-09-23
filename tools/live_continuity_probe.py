"""Test local pixel continuity on actual frames, without a model or robot output."""
import json
import time
import uuid
import numpy as np
from pathlib import Path
from reachy_lol.capture import Capture, windows
from reachy_lol.core import Frame
from reachy_lol.cloud import Situation
from reachy_lol.visual_safety import VisualSafety, pixels, stable


def main():
    c=Capture();ws=[w for w in windows() if w['is_game']]
    if len(ws)!=1:raise RuntimeError('Expected one real game window')
    c.select(ws[0]['hwnd']);frames=[]
    for _ in range(30):
        started=time.monotonic();jpeg=c.grab()
        frames.append(Frame(uuid.uuid4().hex,time.monotonic(),jpeg,window_id=c.hwnd))
        time.sleep(max(0,.5-(time.monotonic()-started)))
    # Deliberate test input to isolate the continuity algorithm. Not a safety verdict.
    assumed=Situation(observations=[],inferences=[],unknowns=[],contribution='',outcome='',
        safe=True,meaningful=False,safe_context='base_idle',safety_evidence=[f.id for f in frames[:2]])
    checker=VisualSafety();accepted=checker.accept(assumed,frames[:2])
    accept_reason=checker.reason
    continued=accepted and checker.revalidate(frames,time.monotonic())
    first_change=None
    anchor=pixels(frames[1])
    for frame in frames[2:]:
        current=pixels(frame)
        if not stable(anchor,current):
            diff=np.abs(anchor-current).mean(axis=2)/255
            cells=diff.reshape(9,6,12,8).mean(axis=(1,3))
            row,col=np.unravel_index(cells.argmax(),cells.shape)
            first_change={'after_s':round(frame.at-frames[1].at,3),'mean':float(diff.mean()),
                'changed':float((diff>.10).mean()),'max_cell':float(cells.max()),
                'max_cell_row':int(row),'max_cell_col':int(col),'hud':float(diff[40:52,30:70].mean())}
            break
    result={'source':'actual_game_pixels','classification':'synthetic_for_algorithm_diagnostic_only',
            'audio_output':False,'accepted':accepted,'accept_reason':accept_reason,
            'continuous':bool(continued),'continuity_reason':checker.reason,
            'first_pixel_change':first_change,
            'gaps_ms':[round((b.at-a.at)*1000) for a,b in zip(frames,frames[1:])]}
    Path('evidence/live-continuity-diagnostic.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
