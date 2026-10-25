"""Start Bengali dubbing as soon as each Persian Bale clip is confirmed.

One GitHub artifact and dispatch per clip; Persian publishing stays independent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import requests

_PENDING: list[threading.Thread] = []


def enabled() -> bool:
    return (os.getenv("NETWORK", "persian") == "persian"
            and os.getenv("ENABLE_BN_DUB_INSTANT", "").lower() in ("1", "true", "yes"))


def _transfer_and_trigger(directory: Path, name: str, run_id: int, idx: int):
    try:
        tool = Path(__file__).resolve().with_name("upload_bengali_artifact.cjs")
        # Preserve uploader stderr, retry only failed artifact uploads.
        for attempt in range(1, 4):
            completed = subprocess.run(
                ["node", str(tool), name, str(directory)],
                timeout=240, capture_output=True, text=True,
            )
            if completed.returncode == 0:
                print(completed.stdout[-1200:], flush=True)
                break
            detail = (completed.stderr or completed.stdout or "").strip()[-2400:]
            print(f"Bengali artifact upload attempt {attempt}/3 failed: "
                  f"{detail}", file=sys.stderr, flush=True)
            if attempt == 3:
                raise RuntimeError(f"Artifact upload failed after 3 attempts: {detail}")
            import time
            time.sleep(attempt * 3)
        token = os.getenv("GITHUB_TOKEN", "").strip()
        repository = os.getenv("GITHUB_REPOSITORY", "").strip()
        if not token or not repository or "/" not in repository:
            raise RuntimeError("Missing GitHub dispatch credentials")
        response = requests.post(
            f"https://api.github.com/repos/{repository}/dispatches",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "event_type": "didban_bengali_clip_ready",
                "client_payload": {"run_id": run_id, "clip_index": idx},
            },
            timeout=30,
        )
        if response.status_code != 204:
            raise RuntimeError(f"GitHub dispatch returned HTTP {response.status_code}")
        print(f"Triggered Bengali dubbing: source run={run_id}, clip={idx}", flush=True)
    except Exception as exc:
        print(f"Bengali handoff FAILED clip={idx}: {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def enqueue_after_sent(video: Path, *, index: int, program: str, expert: str,
                       date: str, title: str, start: int, end: int) -> bool:
    if not enabled() or index not in (1, 2):
        return False
    run_str = os.getenv("GITHUB_RUN_ID", "")
    if not run_str.isdecimal() or not os.getenv("GITHUB_TOKEN"):
        print("Bengali handoff skipped: missing Actions identity", file=sys.stderr)
        return False
    src = Path(video)
    if not src.is_file() or src.stat().st_size < 10_000:
        print("Bengali handoff skipped: missing original MP4", file=sys.stderr)
        return False
    run_id = int(run_str)
    stage = Path(tempfile.mkdtemp(prefix="didban_bn_clip_"))
    destination = stage / f"source_{index:02}.mp4"
    try:
        shutil.copyfile(src, destination)
        manifest = {
            "schema": 1, "run_id": str(run_id), "network": "persian",
            "source": "@live_vtv", "destination": "@double_vtv",
            "count": 1, "clip_index": index, "date": date,
            "program_fa": program, "expert_fa": expert,
            "clips": [{"filename": destination.name, "title_fa": title,
                       "start_sec": int(start), "end_sec": int(end)}],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8"
        )
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    thread = threading.Thread(
        target=_transfer_and_trigger,
        args=(stage, f"bengali-clip-{run_id}-{index}", run_id, index),
        name=f"didban-bn-{index}", daemon=False,
    )
    thread.start()
    _PENDING.append(thread)
    print(f"Started per-clip Bengali artifact upload after Persian clip {index}", flush=True)
    return True


def drain_pending(timeout=250):
    for thread in list(_PENDING):
        thread.join(timeout=timeout)
    _PENDING.clear()
