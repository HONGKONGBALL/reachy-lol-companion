"""One controller per robot, called on one persistent asyncio event loop.

Load RecordedMoves before starting the agent, and keep the ReachyMini connection
open for the lifetime of the controller. Imports do not connect to hardware.
"""

import asyncio
import inspect

from .community import COMMUNITY_MOVES

DATASET = "pollen-robotics/reachy-mini-emotions-library"

# Variants are artistic alternatives, not numerical joint-amplitude levels.
CATALOG = {
    "listen": ("专注倾听用户说话", ("attentive1", "attentive2")),
    "think": ("思考答案或等待工具结果", ("thoughtful1", "thoughtful2")),
    "happy": ("表达开心", ("cheerful1",)),
    "celebrate": ("庆祝好消息或任务完成", ("enthusiastic1", "success1")),
    "confused": ("没有理解，需要澄清", ("confused1",)),
    "surprised": ("对意外信息感到惊讶", ("surprised1", "surprised2")),
    "sad": ("表达难过或失落", ("sad1", "downcast1")),
    "reassure": ("安抚对方", ("calming1",)),
    "agree": ("点头表示理解和同意", ("understanding2",)),
    "greet": ("友好地打招呼", ("welcoming1", "welcoming2")),
}


def _schema(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS = [
    _schema("list_expression_skills", "列出社区开发者预设 skills，以及官方基础动作、来源和加载状态。优先按场景选择合适的社区 skill。"),
    _schema(
        "play_expression_skill",
        "播放社区开发者已预设的动作，通过 list_expression_skills 查看情绪、作者和来源。",
        {
            "skill_id": {"type": "string", "enum": list(COMMUNITY_MOVES)},
            "sound": {"type": "boolean", "default": False},
        },
        ["skill_id"],
    ),
    _schema(
        "express_emotion",
        "让 Reachy Mini 表达一种情绪。等待动作结束后返回；忙碌时返回 busy。",
        {
            "emotion": {"type": "string", "enum": list(CATALOG)},
            "variant": {
                "type": "integer", "minimum": 0, "default": 0,
                "description": "动作变体下标；通过 list_expression_skills 查询。不是强度。",
            },
            "sound": {"type": "boolean", "default": False,
                      "description": "播放动作自带音效；与 TTS 同时使用时通常关闭。"},
        },
        ["emotion"],
    ),
    _schema("stop_expression", "请求停止此控制器正在播放的情绪动作。"),
    _schema("expression_status", "查询此控制器当前动作及预演状态。"),
]


class ExpressionTools:
    """Framework-neutral async tools; dry-run requires only the standard library."""

    def __init__(self, robot=None, library=None, *, dry_run=True):
        if not dry_run and (robot is None or library is None):
            raise ValueError("Live mode requires both a robot and a preloaded library")
        if not dry_run and not all(
            callable(getattr(robot, name, None))
            for name in ("async_play_move", "cancel_move")
        ):
            raise ValueError("SDK must provide async_play_move and cancel_move; upgrade reachy-mini")
        self.robot = robot
        self.library = library
        self.dry_run = dry_run
        self._active = None
        self._stop_requested = False
        self._available = set(library.list_moves()) if library is not None else None

    def list_expression_skills(self):
        return {
            "community_skills": [
                {**spec, "available": None if self._available is None else skill_id in self._available}
                for skill_id, spec in COMMUNITY_MOVES.items()
            ],
            "dataset": DATASET,
            "verified_against_loaded_library": self._available is not None,
            "skills": [
                {
                    "emotion": emotion, "description": description,
                    "variants": [
                        {"variant": i, "move": move,
                         "available": None if self._available is None else move in self._available}
                        for i, move in enumerate(moves)
                    ],
                }
                for emotion, (description, moves) in CATALOG.items()
            ],
        }

    def expression_status(self):
        return {"status": "playing" if self._active else "idle",
                "active": dict(self._active) if self._active else None,
                "stop_requested": self._stop_requested, "dry_run": self.dry_run}

    async def express_emotion(self, emotion, variant=0, sound=False):
        if not isinstance(emotion, str) or emotion not in CATALOG:
            return {"status": "error", "error": "Unknown emotion", "allowed": list(CATALOG)}
        moves = CATALOG[emotion][1]
        if type(variant) is not int or not 0 <= variant < len(moves):
            return {"status": "error", "error": "Invalid variant", "variants": len(moves)}
        if type(sound) is not bool:
            return {"status": "error", "error": "sound must be a boolean"}
        if self._active:
            return {"status": "busy", "active": dict(self._active)}
        move_name = moves[variant]
        selection = {"emotion": emotion, "move": move_name, "sound": sound, "dataset": DATASET}
        return await self._play(move_name, selection, sound)

    async def play_expression_skill(self, skill_id, sound=False):
        if not isinstance(skill_id, str) or skill_id not in COMMUNITY_MOVES:
            return {"status": "error", "error": "Unknown community skill", "allowed": list(COMMUNITY_MOVES)}
        if type(sound) is not bool:
            return {"status": "error", "error": "sound must be a boolean"}
        spec = COMMUNITY_MOVES[skill_id]
        selection = {"skill_id": skill_id, "emotion": spec["emotion"], "move": skill_id,
                     "sound": sound, "dataset": spec["repo_id"], "revision": spec["revision"],
                     "filename": spec["filename"]}
        return await self._play(skill_id, selection, sound)

    async def _play(self, move_name, selection, sound):
        if self._active:
            return {"status": "busy", "active": dict(self._active)}
        if self._available is not None and move_name not in self._available:
            return {"status": "error", "error": "Move missing from loaded library", **selection}
        if self.dry_run:
            return {"status": "dry_run", **selection}

        # There is no await between the busy check and setting active state.
        self._active = selection
        self._stop_requested = False
        try:
            move = self.library.get(move_name)
            if sound and move_name in COMMUNITY_MOVES and COMMUNITY_MOVES[move_name]["audio_filename"]:
                if getattr(move, "sound_path", None) is None:
                    return {"status": "error", "error": "Reload community library with with_audio=True", **selection}
            await self.robot.async_play_move(move, initial_goto_duration=0.5, sound=sound)
            return {"status": "stopped" if self._stop_requested else "completed", **selection}
        except asyncio.CancelledError:
            self.robot.cancel_move()
            raise
        except Exception as exc:
            # A playback exception may leave audio running; cancel it as well.
            try:
                self.robot.cancel_move()
            except Exception:
                pass
            return {"status": "error", "error": str(exc), **selection}
        finally:
            self._active = None
            self._stop_requested = False

    def stop_expression(self):
        if self._active is None:
            return {"status": "idle"}
        try:
            self.robot.cancel_move()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
        self._stop_requested = True
        return {"status": "stop_requested"}

    async def call_tool(self, name, arguments=None):
        """Dispatch decoded function-call arguments without eval or arbitrary getattr."""
        handlers = {
            "list_expression_skills": self.list_expression_skills,
            "play_expression_skill": self.play_expression_skill,
            "express_emotion": self.express_emotion,
            "stop_expression": self.stop_expression,
            "expression_status": self.expression_status,
        }
        if not isinstance(name, str) or name not in handlers:
            return {"status": "error", "error": "Unknown tool"}
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return {"status": "error", "error": "Arguments must be an object"}
        handler = handlers[name]
        try:
            inspect.signature(handler).bind(**arguments)
        except TypeError as exc:
            return {"status": "error", "error": str(exc)}
        result = handler(**arguments)
        return await result if inspect.isawaitable(result) else result
