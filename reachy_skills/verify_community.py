"""Check pinned remote motion files without the robot SDK or hardware."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from .community import COMMUNITY_MOVES, SOURCES, validate_trajectory


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                return response.read()
        except OSError:
            if attempt == 2:
                raise


def verify_one(spec, paths):
    result = {k: spec[k] for k in ("skill_id", "repo_id", "revision", "filename", "audio_filename")}
    try:
        for filename in (spec["filename"], spec["audio_filename"]):
            if filename and filename not in paths:
                raise ValueError(f"File missing at pinned revision: {filename}")
        url = f"https://huggingface.co/datasets/{spec['repo_id']}/resolve/{spec['revision']}/{spec['filename']}"
        raw = fetch(url)
        data = json.loads(raw)
        result.update(validate_trajectory(data))
        result.update(status="valid", sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    except Exception as exc:
        result.update(status="error", error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="docs/community-validation.json")
    args = parser.parse_args()
    inventories = {}
    sources = []
    for repo, revision in SOURCES.values():
        info = json.loads(fetch(f"https://huggingface.co/api/datasets/{repo}/revision/{revision}"))
        if info["sha"] != revision:
            raise ValueError(f"Unexpected revision for {repo}")
        license_name = info.get("cardData", {}).get("license")
        if license_name != "apache-2.0":
            raise ValueError(f"Unexpected license metadata for {repo}: {license_name}")
        inventories[repo] = {item["rfilename"] for item in info["siblings"]}
        sources.append({"repo_id": repo, "revision": revision, "license": license_name})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda s: verify_one(s, inventories[s["repo_id"]]), COMMUNITY_MOVES.values()))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Pinned files, audio file existence, license metadata, finite SDK trajectory structure; no hardware execution or audio content validation",
        "sources": sources, "moves": results,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [r for r in results if r["status"] != "valid"]
    print(json.dumps({"sources": len(sources), "valid": len(results) - len(failures),
                      "errors": failures, "report": str(path)}, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
