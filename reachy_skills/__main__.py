import argparse
import asyncio
import json
import sys

from .expressions import CATALOG, DATASET, TOOL_SCHEMAS, ExpressionTools
from .community import COMMUNITY_MOVES, load_community_library


def main():
    parser = argparse.ArgumentParser(description="Reachy Mini emotion tools (dry-run by default)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("schema")
    preload = commands.add_parser("preload", help="Download/cache moves; no robot connection")
    preload.add_argument("--community", action="store_true", help="Load community presets instead of the official library")
    preload.add_argument("--sound", action="store_true", help="Also download community audio")
    express = commands.add_parser("express")
    express.add_argument("emotion", choices=CATALOG)
    express.add_argument("--variant", type=int, default=0)
    community = commands.add_parser("play", help="Play a community developer's preset skill")
    community.add_argument("skill_id", choices=COMMUNITY_MOVES)
    for play in (express, community):
        play.add_argument("--sound", action="store_true")
        play.add_argument("--live", action="store_true", help="Connect to the robot and perform the motion")
        play.add_argument("--host", default="reachy-mini.local")
        play.add_argument("--port", type=int, default=8000)
        play.add_argument("--connection-mode", choices=["auto", "network", "localhost_only"], default="network")
    args = parser.parse_args()
    try:
        if args.command == "schema":
            result = TOOL_SCHEMAS
        elif args.command == "list":
            result = ExpressionTools().list_expression_skills()
        elif args.command == "preload":
            if args.community:
                library = load_community_library(with_audio=args.sound)
            else:
                from reachy_mini.motion.recorded_move import RecordedMoves
                library = RecordedMoves(DATASET)
            result = ExpressionTools(library=library).list_expression_skills()
            missing = ([s["skill_id"] for s in result["community_skills"] if not s["available"]]
                       if args.community else
                       [v["move"] for s in result["skills"] for v in s["variants"] if not v["available"]])
            result.update(status="error" if missing else "ready", missing=missing)
        else:
            # Validate arguments before importing the SDK or opening a connection.
            tool_name = "play_expression_skill" if args.command == "play" else "express_emotion"
            arguments = ({"skill_id": args.skill_id, "sound": args.sound} if args.command == "play" else
                         {"emotion": args.emotion, "variant": args.variant, "sound": args.sound})
            result = asyncio.run(ExpressionTools().call_tool(tool_name, arguments))
            if args.live and result["status"] != "error":
                from reachy_mini import ReachyMini
                if args.command == "play":
                    library = load_community_library([args.skill_id], with_audio=args.sound)
                else:
                    from reachy_mini.motion.recorded_move import RecordedMoves
                    library = RecordedMoves(DATASET)
                with ReachyMini(host=args.host, port=args.port, connection_mode=args.connection_mode) as robot:
                    tools = ExpressionTools(robot, library, dry_run=False)
                    result = asyncio.run(tools.call_tool(tool_name, arguments))
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
