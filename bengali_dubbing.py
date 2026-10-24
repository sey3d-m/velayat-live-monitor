"""CPU-only Bengali audio dubbing for two verified Persian Didban clips.

Runs in its own GitHub Actions workflow. Never touches the Persian channel.
Models: M2M100 418M (MIT), Bangla male Coqui VITS (MIT).
Fail closed: if one clip is unusable, do not publish either clip.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SOURCE_DIR = Path("bengali_dub_input")
OUTPUT_DIR = Path("bengali_dub_output")
TARGET = "@double_vtv"
MODEL_MT = "facebook/m2m100_418M"
MODEL_TTS = "bangla-speech-processing/bangla_tts_male"
BENGALI = re.compile(r"[\u0980-\u09ff]")


def run_ffmpeg(*args):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=240)


def clip_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return float(result.stdout.strip())


def validate_manifest(manifest):
    if manifest.get("schema") != 1 or manifest.get("network") != "persian":
        raise ValueError("Unexpected source manifest")
    if manifest.get("source") != "@live_vtv" or manifest.get("destination") != TARGET:
        raise ValueError("Channel route validation failed")
    if manifest.get("count") != 2 or len(manifest.get("clips", [])) != 2:
        raise ValueError("Exactly two clips are required")
    expected_run = os.environ.get("ORIGIN_RUN_ID", "").strip()
    if expected_run and str(manifest.get("run_id")) != expected_run:
        raise ValueError("Origin workflow run mismatch")
    for item in manifest["clips"]:
        if not re.fullmatch(r"source_\d{2}\.mp4", item.get("filename", "")):
            raise ValueError("Unexpected source clip filename")
        src = SOURCE_DIR / item["filename"]
        if not src.is_file() or src.stat().st_size < 10_000:
            raise FileNotFoundError(src)
    if manifest["clips"][0]["filename"] == manifest["clips"][1]["filename"]:
        raise ValueError("Duplicate clip source")
    return manifest


def load_asr():
    from faster_whisper import WhisperModel
    return WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=3)


def get_segments(model, path):
    segments, info = model.transcribe(
        str(path), language="fa", beam_size=3, vad_filter=True,
        condition_on_previous_text=False,
    )
    rows = []
    for s in segments:
        text = re.sub(r"\s+", " ", s.text).strip()
        if text and s.end > s.start:
            rows.append({"start": float(s.start), "end": float(s.end), "fa": text})
    if not rows:
        raise ValueError("No Persian speech detected")
    merged = []
    # Longer turns yield more contextual, stable translations and reduce TTS calls.
    for s in rows:
        if (merged and s["start"] - merged[-1]["end"] < 0.8
                and s["end"] - merged[-1]["start"] <= 18
                and len(merged[-1]["fa"] + s["fa"]) <= 200):
            merged[-1]["end"] = s["end"]
            merged[-1]["fa"] += " " + s["fa"]
        else:
            merged.append(dict(s))
    return merged


class Translator:
    def __init__(self):
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        torch.set_num_threads(3)
        self.tok = M2M100Tokenizer.from_pretrained(MODEL_MT)
        self.tok.src_lang = "fa"
        self.model = M2M100ForConditionalGeneration.from_pretrained(MODEL_MT).eval()

    def translate(self, value):
        import torch
        text = re.sub(r"\s+", " ", value).strip()
        if not text:
            return ""
        tokens = self.tok(text, return_tensors="pt", truncation=True, max_length=220)
        with torch.inference_mode():
            generated = self.model.generate(
                **tokens, forced_bos_token_id=self.tok.get_lang_id("bn"),
                max_new_tokens=260, num_beams=3,
            )
        result = self.tok.batch_decode(generated, skip_special_tokens=True)[0].strip()
        if len(BENGALI.findall(result)) < 4:
            raise ValueError("Translation does not contain sufficient Bengali script")
        return result


class MaleTTS:
    def __init__(self):
        import torch
        from huggingface_hub import hf_hub_download
        from TTS.utils.synthesizer import Synthesizer
        torch.set_num_threads(3)
        checkpoint = hf_hub_download(MODEL_TTS, "pytorch_model.pth")
        config = hf_hub_download(MODEL_TTS, "config.json")
        # Use the native Coqui API to load the publisher's original male voice.
        self.synth = Synthesizer(
            tts_checkpoint=str(checkpoint), tts_config_path=str(config),
            use_cuda=False,
        )

    def save(self, text, path):
        value = text.strip()
        if not value.endswith(("।", ".", "?", "!", "।")):
            value += "।"
        audio = self.synth.tts(value)
        self.synth.save_wav(audio, str(path))
        if not path.is_file() or path.stat().st_size < 2000:
            raise ValueError("Synthesized male Bengali speech was empty")


def make_timeline(src, turns, mt, tts, directory, duration):
    import numpy as np
    import soundfile as sf
    sample_rate = 22050
    target = np.zeros(int(duration * sample_rate), dtype=np.float32)
    written = 0
    for index, turn in enumerate(turns):
        bn = mt.translate(turn["fa"])
        turn["bn"] = bn
        start = max(0.0, turn["start"])
        end = min(duration, turn["end"])
        next_start = (turns[index + 1]["start"]
                      if index + 1 < len(turns) else duration)
        allowed = max(0, min(duration, next_start) - start)
        if allowed < 0.35:
            raise ValueError("ASR segment too short to dub")
        generated = directory / f"raw_{index:03}.wav"
        tts.save(bn, generated)
        natural = clip_duration(generated)
        # Preserve the source's time grid. Too much speed-up degrades
        # comprehensibility; fail rather than truncate Bengali utterances.
        ratio = natural / allowed
        if ratio > 2.0:
            raise ValueError(f"Bengali speech overrun: {ratio:.2f}x")
        speed = max(1.0, ratio)
        fitted = directory / f"fit_{index:03}.wav"
        run_ffmpeg("-i", generated, "-af", f"atempo={speed:.6f}",
                   "-ar", sample_rate, "-ac", "1", fitted)
        wave, rate = sf.read(str(fitted), dtype="float32")
        if rate != sample_rate or wave.ndim != 1:
            raise ValueError("Unexpected TTS sample rate or channel count")
        position = int(start * sample_rate)
        available = min(
            len(wave), max(0, int(min(duration, next_start) * sample_rate) - position)
        )
        if available <= 0 or available < 0.93 * len(wave):
            raise ValueError("Audio alignment overflow")
        target[position:position + available] += wave[:available] * 0.92
        written += available
    if written < int(sample_rate * duration * 0.18):
        raise ValueError("Too little synthesized Bengali speech")
    wavefile = directory / "dub_track.wav"
    sf.write(str(wavefile), np.clip(target, -1, 1), sample_rate)
    return wavefile


def render_clip(source, wavefile, output, duration):
    # Video is stream-copied: original pixels, 1x playback speed, no lip sync.
    run_ffmpeg("-i", source, "-i", wavefile, "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
               "-t", f"{duration:.3f}", "-movflags", "+faststart", output)
    if not output.is_file() or output.stat().st_size < 10_000:
        raise ValueError("Dubbed video was not produced")
    if output.stat().st_size > 49 * 1024 * 1024:
        raise ValueError("Dubbed video exceeds Bale upload safety limit")
    if not 0.95 <= clip_duration(output) / duration <= 1.05:
        raise ValueError("Dubbed video duration mismatch")


def send_video(token, path, caption):
    import requests
    endpoint = f"https://tapi.bale.ai/bot{token}/sendVideo"
    for attempt in range(3):
        try:
            with path.open("rb") as handle:
                response = requests.post(
                    endpoint,
                    data={"chat_id": TARGET, "caption": caption[:900],
                          "supports_streaming": "true"},
                    files={"video": (path.name, handle, "video/mp4")},
                    timeout=180,
                )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok") is True:
                return payload.get("result", {}).get("message_id")
            raise RuntimeError("Bale API rejected video")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def main():
    token = os.environ.get("BALE_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BALE_BOT_TOKEN not configured")
    manifest = validate_manifest(json.loads(
        (SOURCE_DIR / "manifest.json").read_text(encoding="utf-8")))
    OUTPUT_DIR.mkdir(exist_ok=True)
    asr = load_asr()
    translator = Translator()
    male_tts = MaleTTS()
    output = []
    # Process BOTH fully before sending either to avoid half-baked publication.
    for num, item in enumerate(manifest["clips"], 1):
        source = SOURCE_DIR / item["filename"]
        duration = clip_duration(source)
        if duration < 15 or duration > 605:
            raise ValueError("Clip duration outside safe range")
        folder = OUTPUT_DIR / f"work_{num:02}"
        folder.mkdir(exist_ok=True)
        wave = folder / "persian.wav"
        run_ffmpeg("-i", source, "-vn", "-ar", "16000", "-ac", "1", wave)
        turns = get_segments(asr, wave)
        dubbed_audio = make_timeline(source, turns, translator, male_tts, folder, duration)
        video = OUTPUT_DIR / f"bengali_{num:02}.mp4"
        render_clip(source, dubbed_audio, video, duration)
        title = translator.translate(item.get("title_fa", "") or "گزیده برنامه")
        output.append((video, title))
        print(f"Bengali clip {num} prepared ({duration:.1f}s); not yet published")
    # Do not transmit Farsi report messages or change their routing.
    results = []
    for index, (video, title) in enumerate(output, 1):
        caption = (f"🎬 {title}\n"
                   f"📺 মিডিয়া মিহির | দিদবান বাংলা\n"
                   f"🎙️ বাংলা পুরুষ কণ্ঠে ডাবিং\n"
                   f"📅 {manifest.get('date', '')}\n"
                   f"#{'দিদবান'} #বাংলা_ডাবিং #মিহির_টিভি")
        ident = send_video(token, video, caption)
        results.append({"clip": index, "message_id": ident, "size": video.stat().st_size})
        print(f"Bengali clip {index} posted to {TARGET}")
    (OUTPUT_DIR / "delivery.json").write_text(json.dumps(
        {"run_id": manifest.get("run_id"), "destination": TARGET,
         "status": "sent", "sent": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("Bengali dubbed clips: 2/2 delivered")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"BENGALI_DUBBING_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
