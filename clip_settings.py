"""Public, strictly validated clip-only settings; never changes report routing."""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "didban_clips.json"
NETWORKS = ("persian", "azeri", "arabic", "hausa")

def load_clip_settings():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if cfg.get("reports") != {"route": "existing_unchanged"}:
        raise ValueError("Report routing is immutable")
    c = cfg["clips"]
    if c.get("destination") != "@live_vtv":
        raise ValueError("Clip destination must remain @live_vtv")
    count, lower, upper = c["count_per_program"], c["min_seconds"], c["max_seconds"]
    if not (type(count) is int and 1 <= count <= 12):
        raise ValueError("Clip count out of range")
    if not (type(lower) is int and type(upper) is int and 15 <= lower <= upper <= 1800):
        raise ValueError("Invalid clip duration")
    if c["quality"] not in ("720p", "1080p") or float(c["speed"]) not in (0.75, 1.0, 1.25, 1.5):
        raise ValueError("Invalid quality or speed")
    if not (type(c["crf"]) is int and 18 <= c["crf"] <= 28):
        raise ValueError("Invalid CRF")
    if c["audio_bitrate_kbps"] not in (96, 128, 160, 192):
        raise ValueError("Invalid audio bitrate")
    if not (type(c["max_upload_mb"]) is int and 10 <= c["max_upload_mb"] <= 49):
        raise ValueError("Invalid upload limit")
    if type(c["enabled"]) is not bool or set(c["networks"]) != set(NETWORKS):
        raise ValueError("Invalid network selection")
    if not all(type(value) is bool for value in c["networks"].values()):
        raise ValueError("Invalid network flags")
    return c
