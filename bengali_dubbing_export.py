"""Export exactly two already-sent Persian clips for asynchronous Bengali dubbing.

The live monitor never depends on this optional handoff; it is deliberately
called after the main monitoring function and before local video cleanup.
"""
import json
import os
import re
import shutil
from pathlib import Path

SOURCE = Path("private_live_video")
OUT = Path("bengali_dub_input")


def export_for_dubbing():
    if os.getenv("ENABLE_BN_DUB_EXPORT", "false").lower() not in ("1", "true", "yes"):
        return False
    report = Path("program_report.json")
    if not report.is_file():
        return False
    data = json.loads(report.read_text(encoding="utf-8"))
    if data.get("network") != "persian":
        return False
    sent = data.get("video_clips", {}).get("sent", [])
    # All-or-nothing for the configured two-clip edition; avoid misleading
    # single-clip publication or accidentally exporting failed clips.
    if len(sent) < 2:
        print("Bengali export: fewer than two successfully sent Persian clips")
        return False
    selected = sent[:2]
    prepared = []
    for item in selected:
        name = item.get("filename", "")
        if not re.fullmatch(r"clip_\\d{2}\\.mp4", name):
            raise ValueError("Unsafe or missing Persian clip file name")
        src = SOURCE / name
        if not src.is_file() or src.stat().st_size < 10_000:
            raise FileNotFoundError(src)
        prepared.append((item, src))
    OUT.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, (item, src) in enumerate(prepared, 1):
        dest = OUT / f"source_{index:02}.mp4"
        shutil.copyfile(src, dest)
        clips.append({
            "filename": dest.name,
            "start_sec": item["start_sec"],
            "end_sec": item["end_sec"],
            "title_fa": item["title"],
            "size_bytes": dest.stat().st_size,
        })
    manifest = {
        "schema": 1,
        "run_id": str(data.get("run_id") or ""),
        "network": "persian",
        "source": "@live_vtv",
        "destination": "@double_vtv",
        "count": 2,
        "date": data.get("date", ""),
        "program_fa": data.get("program", ""),
        "expert_fa": data.get("analysis", {}).get("expert", "") or "",
        "clips": clips,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Bengali dubbing: exported exactly 2 successful Persian clips")
    return True


if __name__ == "__main__":
    export_for_dubbing()
