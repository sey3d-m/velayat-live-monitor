"""Align independently opened live streams before applying editorial timecodes.

The report timeline is produced from program_audio_backup.flac. The MP4 is
recorded from a second live connection, which can begin several seconds later.
Never treat these two zero points as interchangeable without verification.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

SAMPLE_RATE = 2000


def probe_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ], capture_output=True, text=True, timeout=30, check=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def _audio_samples(path, start, seconds):
    import numpy as np
    result = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(path), "-t", f"{seconds:.3f}",
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "f32le", "pipe:1",
    ], capture_output=True, timeout=120, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32).astype(np.float64)


def _best_lag(reference, recording):
    """FFT normalized cross-correlation on high-pass PCM speech."""
    import numpy as np
    if len(reference) < SAMPLE_RATE * 5 or len(recording) < len(reference):
        return None
    ref = np.diff(reference)
    target = np.diff(recording)
    ref -= ref.mean()
    target -= target.mean()
    power = float(np.dot(ref, ref))
    if power < 0.0001:
        return None
    total = len(target) + len(ref) - 1
    nfft = 1 << (total - 1).bit_length()
    correlation = np.fft.irfft(
        np.fft.rfft(target, nfft) *
        np.conjugate(np.fft.rfft(ref, nfft)), nfft
    )[:len(target) - len(ref) + 1]
    squares = np.r_[0., np.cumsum(target * target)]
    target_powers = squares[len(ref):] - squares[:-len(ref)]
    scores = correlation / np.sqrt(
        np.maximum(target_powers * power, 1e-9))
    best = int(np.argmax(scores))
    return best / SAMPLE_RATE, float(scores[best])


def align_video_to_audio(video_file, reference_audio, *, minimum_score=0.32):
    """Return video-second minus transcript-second, or None if uncertain.

    A positive offset means the same phrase occurs later in the MP4's clock.
    A negative offset means the MP4 started after the audio transcript.
    Two widely separated speech anchors must agree within 1.5 seconds.
    """
    if not Path(video_file).exists() or not Path(reference_audio).exists():
        return None
    try:
        video_seconds = probe_duration(video_file)
        audio_seconds = probe_duration(reference_audio)
        if video_seconds < 50 or audio_seconds < 50:
            print("Clip alignment: source too short", file=sys.stderr)
            return None
        anchors = [min(100., audio_seconds * 0.2),
                   min(audio_seconds - 28., audio_seconds * 0.65)]
        measurements = []
        for anchor in anchors:
            # Search a 4-minute window around a 20-second audio fingerprint.
            start = max(0., anchor - 120.)
            stop = min(video_seconds, anchor + 140.)
            ref = _audio_samples(reference_audio, anchor, 20.)
            footage = _audio_samples(video_file, start, stop - start)
            match = _best_lag(ref, footage)
            if match is None or match[1] < minimum_score:
                print(f"Clip alignment unverified at {anchor:.1f}s: {match}",
                      file=sys.stderr)
                return None
            delta = start + match[0] - anchor
            measurements.append(delta)
        if max(measurements) - min(measurements) > 1.5:
            print(f"Clip alignment inconsistent: {measurements}", file=sys.stderr)
            return None
        offset = sum(measurements) / len(measurements)
        print(f"Clip verified A/V timeline offset={offset:+.2f}s "
              f"(matches: {measurements})", flush=True)
        return offset
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, ImportError) as exc:
        print(f"Clip alignment failed ({type(exc).__name__}): {exc}",
              file=sys.stderr)
        return None
