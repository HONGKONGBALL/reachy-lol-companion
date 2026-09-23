import asyncio
import unittest

from reachy_skills import ExpressionTools


class FakeLibrary:
    def list_moves(self):
        return ["cheerful1", "thoughtful1"]

    def get(self, name):
        return name


class FakeRobot:
    def __init__(self):
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.calls = []
        self.cancellations = 0
        self.fail = False

    async def async_play_move(self, move, **kwargs):
        self.calls.append((move, kwargs))
        self.started.set()
        if self.fail:
            raise ConnectionError("robot disconnected")
        await self.finish.wait()

    def cancel_move(self):
        self.cancellations += 1
        self.finish.set()


class ExpressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_is_explicit_and_needs_no_sdk(self):
        tools = ExpressionTools()
        result = await tools.call_tool("express_emotion", {"emotion": "think", "variant": 1})
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["move"], "thoughtful2")
        self.assertFalse(result["sound"])
        self.assertEqual(tools.expression_status()["status"], "idle")
        self.assertFalse(tools.list_expression_skills()["verified_against_loaded_library"])

    async def test_invalid_input_does_not_move_robot(self):
        robot = FakeRobot()
        tools = ExpressionTools(robot, FakeLibrary(), dry_run=False)
        for args in (
            {"emotion": "invented"}, {"emotion": []},
            {"emotion": "happy", "variant": -1},
            {"emotion": "happy", "variant": True},
            {"emotion": "happy", "variant": 1},
            {"emotion": "happy", "sound": "false"},
            {"emotion": "happy", "unexpected": 1}, {},
        ):
            result = await tools.call_tool("express_emotion", args)
            self.assertEqual(result["status"], "error", args)
        self.assertEqual(robot.calls, [])

    async def test_overlap_is_rejected_and_stop_releases_controller(self):
        robot = FakeRobot()
        tools = ExpressionTools(robot, FakeLibrary(), dry_run=False)
        playing = asyncio.create_task(tools.express_emotion("happy"))
        await asyncio.wait_for(robot.started.wait(), 1)
        self.assertEqual(tools.expression_status()["active"]["move"], "cheerful1")
        self.assertEqual((await tools.express_emotion("think"))["status"], "busy")
        self.assertEqual(tools.stop_expression()["status"], "stop_requested")
        self.assertEqual((await asyncio.wait_for(playing, 1))["status"], "stopped")
        self.assertEqual(tools.expression_status()["status"], "idle")
        self.assertEqual((await tools.express_emotion("think"))["status"], "completed")
        self.assertEqual(len(robot.calls), 2)
        self.assertEqual(robot.calls[0][1], {"initial_goto_duration": 0.5, "sound": False})

    async def test_caller_cancellation_stops_motion(self):
        robot = FakeRobot()
        tools = ExpressionTools(robot, FakeLibrary(), dry_run=False)
        playing = asyncio.create_task(tools.express_emotion("happy"))
        await asyncio.wait_for(robot.started.wait(), 1)
        playing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await playing
        self.assertEqual(robot.cancellations, 1)
        self.assertEqual(tools.expression_status()["status"], "idle")

    async def test_playback_failure_cleans_up_and_allows_retry(self):
        robot = FakeRobot()
        tools = ExpressionTools(robot, FakeLibrary(), dry_run=False)
        robot.fail = True
        result = await tools.express_emotion("happy")
        self.assertEqual(result["status"], "error")
        self.assertIn("disconnected", result["error"])
        self.assertEqual(robot.cancellations, 1)
        self.assertEqual(tools.expression_status()["status"], "idle")
        robot.fail = False
        self.assertEqual((await tools.express_emotion("happy"))["status"], "completed")

    async def test_missing_upstream_move_is_not_played(self):
        robot = FakeRobot()
        tools = ExpressionTools(robot, FakeLibrary(), dry_run=False)
        self.assertEqual((await tools.express_emotion("sad"))["status"], "error")
        self.assertEqual(robot.calls, [])

    async def test_tool_dispatch_is_allowlisted(self):
        tools = ExpressionTools()
        self.assertEqual((await tools.call_tool("__init__"))["status"], "error")
        self.assertEqual((await tools.call_tool("express_emotion", []))["status"], "error")
        self.assertEqual((await tools.call_tool("expression_status", {"x": 1}))["status"], "error")
        self.assertEqual((await tools.call_tool("stop_expression"))["status"], "idle")

    async def test_stop_failure_does_not_claim_stopped(self):
        robot = FakeRobot()
        tools = ExpressionTools(robot, FakeLibrary(), dry_run=False)
        playing = asyncio.create_task(tools.express_emotion("happy"))
        await asyncio.wait_for(robot.started.wait(), 1)
        def broken_cancel():
            raise ConnectionError("cancel failed")
        robot.cancel_move = broken_cancel
        self.assertEqual(tools.stop_expression()["status"], "error")
        self.assertFalse(tools.expression_status()["stop_requested"])
        robot.finish.set()
        self.assertEqual((await playing)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
