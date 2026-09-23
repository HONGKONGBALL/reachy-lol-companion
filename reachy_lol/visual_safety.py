"""Short-lived visual safety anchors corroborated by independent pixel checks.

This is a conservative heuristic, not a calibrated combat classifier. Real-game
false positives and missed safe opportunities remain acceptance tests.
"""
import io
import numpy as np
from PIL import Image


def pixels(frame):
    with Image.open(io.BytesIO(frame.jpeg)) as image:
        return np.asarray(image.convert('RGB').resize((96,54)),dtype=np.float32)


def stable(a,b):
    diff=np.abs(a-b).mean(axis=2)/255
    local=diff.reshape(9,6,12,8).mean(axis=(1,3))
    # Include local changes, not just a mean that can hide a small approaching unit.
    return (float(diff.mean())<.015 and float((diff>.10).mean())<.025 and float(local.max())<.06
            and float(diff[40:52,30:70].mean())<.02)


class VisualSafety:
    def __init__(self):
        self.clear()

    def clear(self, reason='cleared'):
        self.reason=reason
        self.anchor=None
        self.source_at=-1000
        self.window_id=None
        self.segment=None
        self.verified_at=-1000

    def accept(self, result, frames):
        self.clear()
        if not result.safe or result.safe_context not in ('base_idle','safe_idle','postgame'):
            self.reason='model_not_safe'
            return False
        ids=set(result.safety_evidence)
        selected=[f for f in frames if f.id in ids]
        if (len(selected)<2 or frames[-1].id not in ids
                or len({(f.window_id,f.segment) for f in selected})!=1):
            self.reason='invalid_evidence'
            return False
        a,b=selected[-2:]
        if not .4<=b.at-a.at<=2.5:
            self.reason='evidence_time_gap'
            return False
        before,after=pixels(a),pixels(b)
        if not stable(before,after):
            self.reason='evidence_pixels_changed'
            return False
        self.anchor=after;self.source_at=b.at
        self.verified_at=b.at
        self.window_id=b.window_id;self.segment=b.segment
        self.reason='accepted'
        return True

    def observe(self, frame):
        for ok,reason in (
            (self.anchor is not None,'no_anchor'),
            (0<=frame.at-self.source_at<=20,'source_expired'),
            (0<=frame.at-self.verified_at<=1.2,'capture_gap'),
            (frame.window_id==self.window_id and frame.segment==self.segment,'scene_changed')):
            if not ok:
                self.clear(reason)
                return False
        if not stable(self.anchor,pixels(frame)):
            self.clear('pixels_changed')
            return False
        self.verified_at=frame.at
        self.reason='continuous'
        return True

    def revalidate(self, frames, now):
        """Account for every captured frame during a slow model request."""
        for frame in frames:
            if frame.at>self.verified_at and not self.observe(frame):
                return False
        if self.anchor is None or not 0<=now-self.verified_at<1.2:
            self.clear('latest_frame_stale')
            return False
        return True
