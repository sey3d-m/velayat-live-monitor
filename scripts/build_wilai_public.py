#!/usr/bin/env python3
"""Build a strict public-only WilAI package. Never bundles staff/private artifacts."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs"
TARGET = ROOT / "_wilai_public"
ATLAS_FILES = {"index.html", "atlas-pro.css", "atlas-pro.js", "overrides.json"}
DATA_ALLOWED = re.compile(r"^(?:index|content-index|archive-20[0-9]{2}|content-20[0-9]{2})\.json$")


def safe_copy(src: Path, dst: Path) -> None:
    if not src.is_file() or src.is_symlink():
        raise ValueError(f"Non-regular file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def build() -> dict[str, int]:
    if TARGET.exists():
        raise ValueError("Output directory already exists; refusing to overwrite it")
    atlas = SOURCE / "atlas"
    data = SOURCE / "data"
    landing = SOURCE / "wilai" / "index.html"
    for required in (landing, atlas / "index.html", data / "index.json", data / "content-index.json"):
        if not required.is_file():
            raise FileNotFoundError(required)

    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    content_index = json.loads((data / "content-index.json").read_text(encoding="utf-8"))
    selected = {"index.json", "content-index.json"}
    for catalog in (index, content_index):
        for year in catalog.get("years", []):
            name = year.get("path", "")
            if not DATA_ALLOWED.fullmatch(name):
                raise ValueError(f"Unexpected archive path: {name}")
            selected.add(name)

    atlas_files = [atlas / name for name in sorted(ATLAS_FILES)]
    if not atlas_files:
        raise ValueError("No Atlas assets found")
    for name in selected:
        json.loads((data / name).read_text(encoding="utf-8"))

    safe_copy(landing, TARGET / "index.html")
    for p in atlas_files:
        safe_copy(p, TARGET / "atlas" / p.name)
    for name in sorted(selected):
        safe_copy(data / name, TARGET / "data" / name)
    return {"atlas_files": len(atlas_files), "data_files": len(selected)}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
