"""Community presets, pinned to inspected HF dataset revisions.

These are external recordings/generated trajectories, not locally invented moves.
Dataset owners' IDs are retained even when a file lives in data/ or moves/.
"""

import json
import math
from pathlib import Path


SOURCES = {
    "anne": ("Anne-Charlotte/new-emotions", "f4ff49c51da612b1680816725dc0a181a11a5693"),
    "stella": ("stellaaaa/thinking-animations", "a7fb5f0b7de631a68b1a982edcb54b9795cc5555"),
    "generated": ("tfrere/reachy-mini-generated-moves", "6d36227d2c425c14477576f09e1b109ea64c1e92"),
    "alive": ("HTurlet15/reachy-alive", "e0ae90e3642ea1e07e4cdb4172290ead869d95a6"),
    "personality": ("tfrere/reachy-personalities", "02ed9f1a478ec19a346e7bec90bb6af83c09e1c1"),
    "apirrone": ("apirrone/marionette-moves", "d97420b711853ab698c13b612eb3ee01ad0b317f"),
    "shivansh": ("ShivanshVikram/happy-dance", "fecbbfb3a0b466c8d07e7c8a72ebc01ec7264389"),
    "pirate": ("Anne-Charlotte/pirate-character", "30c3b10d510e94c9aaf219f278111c8715b34c3b"),
}

# Chinese intent labels are local interpretations of upstream names/descriptions.
_PRESETS = [
    ("anne.chill", "anne", "data/chill", "ogg", "放松、平静", "calm"),
    ("anne.dazed", "anne", "data/dazed", "ogg", "发懵、迷糊", "confused"),
    ("anne.discovering", "anne", "data/discovering", "ogg", "发现新事物", "curious"),
    ("anne.hanging_out", "anne", "data/hanging-out", "ogg", "轻松陪伴", "idle"),
    ("anne.no_way", "anne", "data/no-way", "ogg", "不接受、难以置信", "disagree"),
    ("anne.nodding", "anne", "data/nodding", "ogg", "点头回应", "agree"),
    ("anne.peekaboo", "anne", "data/pick-a-boo", "ogg", "躲猫猫式互动", "playful"),
    ("anne.surprise", "anne", "data/surprise", "ogg", "惊讶", "surprised"),
    ("anne.waiting", "anne", "data/waiting", None, "等待回应", "waiting"),
    ("anne.attention", "anne", "data/calling-for-attention", None, "吸引注意", "attention"),
    ("anne.whistling", "anne", "data/whistling", "ogg", "轻快、吹口哨", "happy"),
    ("stella.think", "stella", "data/head-down-antennae-think", None, "低头思考并活动天线", "think"),
    ("stella.slow_think", "stella", "data/head-down-antennae-slow", None, "缓慢的低头天线动作", "think"),
    ("stella.wiggle", "stella", "data/head-down-antennae-wiggle", None, "低头摆动天线", "playful"),
    ("stella.double_nod", "stella", "data/double-nod", None, "连续点头", "agree"),
    ("stella.slow_nod", "stella", "data/slow-nod", None, "缓慢点头", "listen"),
    ("generated.curious", "generated", "moves/20260820-090516_curious_head_tilt", "ogg", "好奇地歪头", "curious"),
    ("generated.agree", "generated", "moves/20260820-102352_yes_an_enthusiastic_agreeing_nod", "ogg", "热情地点头同意", "agree"),
    ("generated.refuse", "generated", "moves/20260820-102443_no_no_no_a_firm_refusal_head_shake", "ogg", "坚定摇头拒绝", "disagree"),
    ("generated.greet", "generated", "moves/20260820-102605_a_warm_hello_greeting_someone_who_just_w", "ogg", "温暖地打招呼", "greet"),
    ("generated.confused", "generated", "moves/20260820-102655_hm_a_puzzled_head_tilt_didn_t_quite_catc", "ogg", "困惑地歪头", "confused"),
    ("generated.joy", "generated", "moves/20260820-102758_a_burst_of_pure_joy_after_great_news", "ogg", "收到好消息后的喜悦", "happy"),
    ("generated.sigh", "generated", "moves/20260820-102850_a_long_melancholic_sigh_slowly_deflating", "ogg", "低落地叹气", "sad"),
    ("generated.startled", "generated", "moves/20260820-102932_a_startled_jump_when_a_door_slams", "ogg", "受惊的反应", "surprised"),
    ("generated.shy_celebrate", "generated", "moves/20260820-103113_a_shy_but_proud_little_celebration", "ogg", "害羞又自豪地庆祝", "celebrate"),
    ("generated.sassy", "generated", "moves/20260820-094210_an_i_don_t_care_what_you_say_sassy_movem", "ogg", "俏皮、不以为然", "sassy"),
    ("alive.sneeze", "alive", "data/sneezing", "wav", "打喷嚏，增加拟生命感", "sneeze"),
    ("alive.hiccup", "alive", "data/hiccup-full", "wav", "打嗝，增加拟生命感", "hiccup"),
    ("personality.change", "personality", "data/change-personality", None, "人格切换时的过渡动作", "transition"),
    ("apirrone.secret_dance", "apirrone", "data/secret-dance", "wav", "开发者录制的舞蹈", "celebrate"),
    ("shivansh.attention", "shivansh", "data/attention", None, "吸引注意的录制动作", "attention"),
    ("shivansh.attention3", "shivansh", "data/attention-3", "wav", "吸引注意的另一段录制动作", "attention"),
    ("pirate.laugh", "pirate", "data/pirate-laughter", "ogg", "海盗角色的笑声和动作", "laugh"),
    ("pirate.arr", "pirate", "data/pirate-arr", "ogg", "海盗角色的语气动作", "roleplay"),
]

COMMUNITY_MOVES = {}
for skill_id, source, stem, audio_ext, description, emotion in _PRESETS:
    repo, revision = SOURCES[source]
    COMMUNITY_MOVES[skill_id] = {
        "skill_id": skill_id, "description": description, "emotion": emotion,
        "repo_id": repo, "revision": revision, "filename": stem + ".json",
        "audio_filename": stem + "." + audio_ext if audio_ext else None,
        "license": "apache-2.0", "kind": "generated" if source == "generated" else "recorded",
        "url": "https://huggingface.co/datasets/" + repo,
    }


def validate_trajectory(data):
    """Validate SDK data shape, not physical limits or perceived emotion."""
    if not isinstance(data, dict) or not isinstance(data.get("description"), str):
        raise ValueError("Expected recorded-move JSON with description")
    if data.get("audio_only"):
        raise ValueError("Audio-only presets are not robot motion skills")
    times, frames = data.get("time"), data.get("set_target_data")
    if not isinstance(times, list) or not isinstance(frames, list) or len(times) < 2 or len(times) != len(frames):
        raise ValueError("Expected matching time and set_target_data arrays with at least two samples")
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    if not all(number(t) for t in times) or times[0] < 0 or times[-1] <= times[0]:
        raise ValueError("Invalid trajectory timestamps")
    if any(a > b for a, b in zip(times, times[1:])):
        raise ValueError("Timestamps must be nondecreasing")
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("Expected frame object")
        head, antennas = frame.get("head"), frame.get("antennas")
        if not isinstance(head, list) or len(head) != 4 or not all(
            isinstance(row, list) and len(row) == 4 and all(number(v) for v in row) for row in head
        ):
            raise ValueError("Expected finite 4x4 head matrix")
        if not isinstance(antennas, list) or len(antennas) != 2 or not all(number(v) for v in antennas):
            raise ValueError("Expected two finite antenna positions")
        if not number(frame.get("body_yaw", 0.0)):
            raise ValueError("Invalid body yaw")
    return {"samples": len(times), "duration_seconds": times[-1] - times[0]}


class CommunityLibrary:
    """Preloaded Move objects using the same get/list_moves protocol as RecordedMoves."""

    def __init__(self, moves):
        self.moves = dict(moves)

    def list_moves(self):
        return list(self.moves)

    def get(self, name):
        return self.moves[name]


class CombinedLibrary:
    def __init__(self, *libraries):
        self._owners = {}
        for library in libraries:
            for name in library.list_moves():
                if name in self._owners:
                    raise ValueError(f"Duplicate move ID: {name}")
                self._owners[name] = library

    def list_moves(self):
        return list(self._owners)

    def get(self, name):
        return self._owners[name].get(name)


def load_community_library(skill_ids=None, *, with_audio=False, downloader=None, move_factory=None):
    """Download exact files at pinned revisions; never import code from a dataset.

    Run once before the agent starts. get() only reads in-memory Move objects.
    downloader/move_factory are injectable for integration testing without hardware.
    """
    ids = list(COMMUNITY_MOVES) if skill_ids is None else list(skill_ids)
    unknown = set(ids) - COMMUNITY_MOVES.keys()
    if unknown:
        raise ValueError(f"Unknown community skills: {sorted(unknown)}")
    if downloader is None:
        from huggingface_hub import hf_hub_download
        downloader = hf_hub_download
    if move_factory is None:
        from reachy_mini.motion.recorded_move import RecordedMove
        move_factory = RecordedMove
    moves = {}
    for skill_id in ids:
        spec = COMMUNITY_MOVES[skill_id]
        kwargs = {"repo_id": spec["repo_id"], "repo_type": "dataset", "revision": spec["revision"]}
        path = Path(downloader(filename=spec["filename"], **kwargs))
        data = json.loads(path.read_text(encoding="utf-8"))
        validate_trajectory(data)
        audio = None
        if with_audio and spec["audio_filename"]:
            audio = Path(downloader(filename=spec["audio_filename"], **kwargs))
        moves[skill_id] = move_factory(data, sound_path=audio)
    return CommunityLibrary(moves)
