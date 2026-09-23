import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest

from reachy_skills import ExpressionTools, CombinedLibrary, load_community_library
from reachy_skills.community import COMMUNITY_MOVES, CommunityLibrary, validate_trajectory


FRAME = {"head": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
         "antennas": [0, 0], "body_yaw": 0}
MOTION = {"description": "test", "time": [0, 0.1], "set_target_data": [FRAME, FRAME]}


class FakeMove:
    def __init__(self, data, sound_path=None):
        self.data = data
        self.sound_path = sound_path


class CommunityTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_uses_developer_source_not_official_dataset(self):
        tools = ExpressionTools()
        result = await tools.call_tool("play_expression_skill", {"skill_id": "stella.think"})
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["dataset"], "stellaaaa/thinking-animations")
        self.assertEqual(result["filename"], "data/head-down-antennae-think.json")
        self.assertEqual(len(result["revision"]), 40)

    async def test_nested_files_and_audio_use_same_pinned_revision(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            def download(**kwargs):
                calls.append(kwargs)
                path = Path(tmp) / Path(kwargs["filename"]).name
                path.write_text(json.dumps(MOTION) if path.suffix == ".json" else "audio", encoding="utf-8")
                return str(path)
            library = load_community_library(["alive.sneeze"], with_audio=True,
                                             downloader=download, move_factory=FakeMove)
            move = library.get("alive.sneeze")
            self.assertTrue(move.sound_path.is_file())
            self.assertEqual([c["filename"] for c in calls], ["data/sneezing.json", "data/sneezing.wav"])
            self.assertTrue(all(c["revision"] == COMMUNITY_MOVES["alive.sneeze"]["revision"] for c in calls))
            self.assertTrue(all(c["repo_type"] == "dataset" for c in calls))

    async def test_invalid_trajectory_never_reaches_sdk_factory(self):
        data = copy.deepcopy(MOTION)
        data["set_target_data"][0]["antennas"][0] = float("nan")
        with self.assertRaises(ValueError):
            validate_trajectory(data)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            def unexpected_factory(*args, **kwargs):
                self.fail("Invalid file reached SDK")
            with self.assertRaises(ValueError):
                load_community_library(["stella.think"], downloader=lambda **kw: str(path),
                                       move_factory=unexpected_factory)

    async def test_audio_only_preset_is_not_a_motion(self):
        with self.assertRaisesRegex(ValueError, "Audio-only"):
            validate_trajectory({"description": "audio", "audio_only": True,
                                 "time": [0, 1], "set_target_data": []})

    async def test_unknown_skill_rejected_before_any_download(self):
        def unexpected_download(**kwargs):
            self.fail("Unknown skill caused a download")
        with self.assertRaises(ValueError):
            load_community_library(["unknown.skill"], downloader=unexpected_download, move_factory=FakeMove)
        result = await ExpressionTools().call_tool("play_expression_skill", {"skill_id": "unknown.skill"})
        self.assertEqual(result["status"], "error")

    async def test_official_and_community_share_motion_lock_and_stop(self):
        class Robot:
            def __init__(self):
                self.started = asyncio.Event()
                self.finish = asyncio.Event()
                self.played = []
            async def async_play_move(self, move, **kwargs):
                self.played.append(move)
                self.started.set()
                await self.finish.wait()
            def cancel_move(self):
                self.finish.set()
        community_move = FakeMove(MOTION)
        library = CombinedLibrary(CommunityLibrary({"stella.think": community_move}),
                                  CommunityLibrary({"cheerful1": FakeMove(MOTION)}))
        robot = Robot()
        tools = ExpressionTools(robot, library, dry_run=False)
        task = asyncio.create_task(tools.play_expression_skill("stella.think"))
        await asyncio.wait_for(robot.started.wait(), 1)
        self.assertEqual((await tools.express_emotion("happy"))["status"], "busy")
        self.assertEqual(tools.stop_expression()["status"], "stop_requested")
        self.assertEqual((await task)["status"], "stopped")
        self.assertIs(robot.played[0], community_move)
        self.assertEqual((await tools.express_emotion("happy"))["status"], "completed")

    async def test_audio_not_loaded_is_reported(self):
        class Robot:
            async def async_play_move(self, *args, **kwargs):
                raise AssertionError("Should not play without requested audio")
            def cancel_move(self):
                pass
        tools = ExpressionTools(Robot(), CommunityLibrary({"alive.sneeze": FakeMove(MOTION)}), dry_run=False)
        result = await tools.play_expression_skill("alive.sneeze", sound=True)
        self.assertEqual(result["status"], "error")
        self.assertIn("with_audio=True", result["error"])
        self.assertEqual(tools.expression_status()["status"], "idle")

    async def test_missing_community_skill_does_not_fallback_to_official(self):
        tools = ExpressionTools(library=CommunityLibrary({"cheerful1": FakeMove(MOTION)}))
        result = await tools.play_expression_skill("generated.joy")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["dataset"], "tfrere/reachy-mini-generated-moves")

    async def test_duplicate_library_ids_rejected(self):
        library = CommunityLibrary({"same": FakeMove(MOTION)})
        with self.assertRaises(ValueError):
            CombinedLibrary(library, library)


if __name__ == "__main__":
    unittest.main()
