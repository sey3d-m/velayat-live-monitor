"""Sample live video frames alongside existing audio recording; images stay private."""
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from google.genai import types

FRAME_DIR = Path("private_live_frames")
VISUAL_MODEL = os.getenv("VISUAL_REVIEW_MODEL", "").strip() or "gemini-3.8-flash"

def enabled():
    return os.getenv("ENABLE_VISUAL_REVIEW", "true").lower() not in ("0", "false", "off")

def interval_for(duration):
    return max(65, (max(1, duration) + 99) // 100)


def report_image_count():
    """Two pictures by default; allow a third through GitHub Actions variables."""
    try:
        count = int(os.getenv("VISUAL_REPORT_IMAGE_COUNT") or "2")
    except ValueError:
        return 2
    return count if count in (2, 3) else 2


def format_offset_minutes(offset_sec):
    """Nearest elapsed minute, never an absolute on-air clock time."""
    seconds = max(0, int(float(offset_sec or 0)))
    return f"{(seconds + 30) // 60} دقیقه"

async def capture_frames(media_url, duration):
    FRAME_DIR.mkdir(exist_ok=True)
    for old in FRAME_DIR.glob("frame_*.jpg"):
        old.unlink(missing_ok=True)
    interval = interval_for(duration)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
           "-i", media_url, "-map", "0:v:0", "-an", "-t", str(duration),
           "-vf", f"fps=1/{interval},scale=960:-2", "-q:v", "5",
           "-frames:v", "100", "-y", str(FRAME_DIR / "frame_%05d.jpg")]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print("Video snapshot warning: " + stderr.decode("utf8", "replace")[-350:], file=sys.stderr)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"Video snapshots unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
    return [{"path": p, "offset_sec": (i-1)*interval, "offset_approximate": True}
            for i,p in enumerate(sorted(FRAME_DIR.glob("frame_*.jpg")), 1)]

async def capture_audio_and_frames(audio_capture, media_url, duration):
    from video_clips import capture_video, enabled as clips_enabled
    image_task = asyncio.create_task(capture_frames(media_url, duration)) if enabled() else None
    video_task = asyncio.create_task(capture_video(media_url, duration)) if clips_enabled() else None
    tasks = [task for task in (image_task, video_task) if task is not None]
    try:
        plain, timed, meta = await audio_capture()
        frames, video = [], None
        for task, kind in ((image_task, "image"), (video_task, "video")):
            if task is None:
                continue
            try:
                value = await task
                if kind == "image":
                    frames = value
                else:
                    video = value
            except Exception as exc:
                print(f"Visual {kind} capture problem: {exc}", file=sys.stderr)
        return plain, timed, meta, frames, video
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

def timestamp_seconds(stamp):
    parts = [int(x) for x in stamp.split(":")]
    return parts[0]*3600+parts[1]*60+parts[2] if len(parts)==3 else parts[0]*60+parts[1]

def nearby_transcript(timed, offset):
    lines = re.findall(r"\[(\d\d:\d\d(?::\d\d)?)\s*-\s*(\d\d:\d\d(?::\d\d)?)\]\s*([^\n]+)", timed)
    near = sorted(((min(abs(timestamp_seconds(a)-offset),abs(timestamp_seconds(b)-offset)), t)
                   for a,b,t in lines if len(t.strip()) >= 12), key=lambda x:x[0])
    return near[0][1][:280] if near else ""

def select_frames(frames, timed):
    """Pick 2 (or optionally 3) well-spaced frames across the whole programme."""
    n = len(frames)
    if not n:
        return []
    count = min(report_image_count(), n)
    positions = ((0.5,) if count == 1 else
                 (0.30, 0.70) if count == 2 else
                 (0.18, 0.50, 0.82))
    indices = []
    for fraction in positions:
        idx = round((n - 1) * fraction)
        if idx in indices:
            idx = min((i for i in range(n) if i not in indices),
                      key=lambda i: (abs(i - round((n - 1) * fraction)), i))
        indices.append(idx)
    return [{**frames[i], "context": nearby_transcript(timed, frames[i]["offset_sec"])}
            for i in sorted(indices)]

def visual_review(client, frames, timed):
    selected = select_frames(frames,timed)
    if not selected:
        return {"status":"unavailable","note":"تصویری از پخش زنده دریافت نشد.","frames":[]}
    instruction = """تصاویر اسکرین‌شات پخش زنده هستند. فقط پوشش و کیفیت ارائه بصری را از موارد قابل رؤیت بررسی کن:
آراستگی لباس، هماهنگی رنگ پوشش با دکور، مرتب‌بودن یقه و لباس، نور، کادربندی و موانع تصویری.
نکات مناسب را نیز توضیح بده. از یک فریم نمی‌توان گفت چه کسی همان لحظه صحبت می‌کند.
درباره جنسیت، مذهب، قومیت، جذابیت یا وضعیت بدنی داوری نکن.
متن نزدیک فریم فقط کمک زمینه‌ای است؛ زمان تصاویر تقریبی است.
برای هر تصویر JSON فارسی در ساختار زیر تولید کن:
{"frames":[{"frame_index":1,"observation":"مشاهدهٔ عینی","assessment":"ارزیابی حرفه‌ای","recommendation":"پیشنهاد عملی","confidence":"medium"}]}
مقادیر confidence فقط low/medium/high باشند و فراتر از آنچه می‌بینی ادعا نکن.
"""
    parts = [instruction]
    for idx, f in enumerate(selected,1):
        parts.append(f"فریم {idx}؛ ثانیه تقریبی {f['offset_sec']}؛ متن نزدیک: {f['context']}")
        parts.append(types.Part.from_bytes(data=f["path"].read_bytes(),mime_type="image/jpeg"))
    proposed={}; note=""
    try:
        response=client.models.generate_content(
            model=VISUAL_MODEL,contents=parts,
            config=types.GenerateContentConfig(temperature=0.1,response_mime_type="application/json"))
        raw=(response.text or "").strip()
        raw=raw.removeprefix(chr(96)*3+"json").removesuffix(chr(96)*3).strip()
        records=json.loads(raw).get("frames",[])
        for item in records:
            if isinstance(item,dict) and isinstance(item.get("frame_index"),int):
                proposed[item["frame_index"]]=item
    except Exception as exc:
        note=f"تحلیل تصویر در دسترس نبود ({type(exc).__name__})."
        print(f"Vision review failed: {exc}",file=sys.stderr)
    data=[]
    for idx,f in enumerate(selected,1):
        x=proposed.get(idx,{})
        data.append({"path":f["path"],"offset_sec":f["offset_sec"],"offset_approximate":True,
          "observation":str(x.get("observation","تصویر دریافت شد؛ تحلیل در دسترس نیست."))[:500],
          "assessment":str(x.get("assessment",""))[:450],
          "recommendation":str(x.get("recommendation",""))[:450],
          "confidence":x.get("confidence","low") if x.get("confidence") in ("high","medium","low") else "low"})
    return {"status":"reviewed" if proposed else "captured_unreviewed","note":note,"frames":data}

def report_metadata(result):
    return {"status":result.get("status","unavailable"),"note":result.get("note",""),
      "frames":[{k:v for k,v in f.items() if k!="path"} for f in result.get("frames",[])]}


def send_bale_photos(result, token, chat_id, program):
    """Upload both the original snapshot and its associated visual judgement."""
    import requests
    errors=[]
    selected=result.get("frames", [])[:report_image_count()]
    for idx,frame in enumerate(selected,1):
        path=frame["path"]
        caption=(
            f"📸 دیدبان | ارزیابی تصویر {idx} از {len(selected)} | {program}\n"
            f"⏱ حدود {format_offset_minutes(frame['offset_sec'])} از شروع ضبط\n"
            f"🔎 مشاهده: {frame['observation']}\n"
            f"🧥 ارزیابی: {frame['assessment'] or 'نامشخص'}\n"
            f"💡 پیشنهاد: {frame['recommendation'] or 'مورد مشخصی ثبت نشد'}"
        )[:900]
        err=None
        for attempt in range(2):
            try:
                with path.open("rb") as photo:
                    response=requests.post(
                        f"https://tapi.bale.ai/bot{token}/sendPhoto",
                        data={"chat_id":chat_id,"caption":caption},
                        files={"photo":(path.name,photo,"image/jpeg")},timeout=45)
                if response.status_code!=200 or response.json().get("ok") is not True:
                    raise RuntimeError("Bale rejected screenshot")
                err=None
                break
            except Exception as exc:
                err=exc
                print(f"Bale photo {idx} attempt {attempt+1}: {exc}",file=sys.stderr)
        if err:
            errors.append(f"photo_{idx}: {type(err).__name__}: {err}")
    return errors
