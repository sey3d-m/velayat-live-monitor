"""Stage the first two **published** Persian viral clips for Bengali dubbing.

A child shell has no ACTIONS_RUNTIME_TOKEN on GitHub hosted runners, so it
cannot use the @actions/artifact SDK directly. The official upload-artifact
workflow steps upload these files and dispatch the dubbed runs reliably.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

STAGE_ROOT = Path("bengali_stage")


def enabled() -> bool:
    return (os.getenv("NETWORK", "persian") == "persian"
            and os.getenv("ENABLE_BN_DUB_INSTANT", "").lower() in ("1", "true", "yes"))


def enqueue_after_sent(video: Path, *, index: int, program: str, expert: str,
                       date: str, title: str, start: int, end: int) -> bool:
    """Persist only MP4 files that were confirmed sent to @live_vtv.

    Workflow uploads per clip, then repository_dispatch starts independent
    processing of that exact MP4. No new transcript selection takes place.
    """
    if not enabled() or index not in (1, 2):
        return False
    run_str = os.getenv("GITHUB_RUN_ID", "")
    if not run_str.isdecimal():
        print("Bengali handoff skipped: missing Actions run ID", file=sys.stderr)
        return False
    src = Path(video)
    if not src.is_file() or src.stat().st_size < 10_000:
        print("Bengali handoff skipped: missing original MP4", file=sys.stderr)
        return False
    stage = STAGE_ROOT / f"clip_{index:02}"
    stage.mkdir(parents=True, exist_ok=True)
    dest = stage / f"source_{index:02}.mp4"
    shutil.copyfile(src, dest)
    manifest = {
        "schema": 1, "run_id": run_str, "network": "persian",
        "source": "@live_vtv", "destination": "@double_vtv",
        "count": 1, "clip_index": index, "date": date,
        "program_fa": program, "expert_fa": expert,
        "clips": [{
            "filename": dest.name, "title_fa": title,
            "start_sec": int(start), "end_sec": int(end),
        }],
    }
    (stage / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Bengali handoff staged confirmed viral clip {index} "
          f"({start}-{end}s): {dest.stat().st_size} bytes", flush=True)
    return True


def drain_pending(timeout=250):
    """Compatibility hook; staging is synchronous, no upload thread remains."""
    return None
