import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import jdatetime
from google import genai
from pydantic import BaseModel, Field

TEHRAN = ZoneInfo('Asia/Tehran')
STREAM_URL = os.environ.get('STREAM_URL', '').strip()
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
SHEETS_WEBHOOK_URL = os.environ.get('SHEETS_WEBHOOK_URL', '').strip()
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', '').strip()
BALE_BOT_TOKEN = os.environ.get('BALE_BOT_TOKEN', '').strip()
BALE_CHAT_ID = os.environ.get('BALE_CHAT_ID', '').strip()
GITHUB_RUN_ID = os.environ.get('GITHUB_RUN_ID', 'manual')

CAPTURE_SECONDS = 3595
AUDIO_FILE = Path('one_hour_test_audio.mp3')
TRANSCRIPT_FILE = Path('one_hour_test_transcript.txt')
REPORT_FILE = Path('one_hour_test_report.json')

ANALYSIS_MODELS = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash']
CUSTOM_VOCABULARY = [
    'شبکه جهانی ولایت','زمزم احکام','آفتاب و سایه ها','پرسمان اعتقادی',
    'امت اسلام','بیان امیر','فائزون','فرکانس تاریکی','پرسمان مذاهب',
    'کانون مهر','پیام تاریخ','پرسمان قرآنی','چراغ','پرسمان تاریخی',
    'گامی به سوی ظهور','حیات قرآنی','اهل‌بیت','امیرالمؤمنین','حضرت زهرا',
    'امام زمان','مهدویت','اهل‌سنت','قرآن کریم','نهج‌البلاغه'
]

class AudienceQuestion(BaseModel):
    source_type: Literal['phone', 'message', 'unknown']
    audience_name: str
    question: str
    answer_summary: str

class ProgramAnalysis(BaseModel):
    expert: str = Field(description='نام کارشناس؛ در صورت نامشخص بودن «نامشخص»')
    topic: str
    summary: str
    key_points: list[str]
    audience_questions: list[AudienceQuestion]

def fail(msg):
    raise RuntimeError(msg)

def check_secrets():
    required = {
        'STREAM_URL': STREAM_URL,
        'GEMINI_API_KEY': GEMINI_API_KEY,
        'SHEETS_WEBHOOK_URL': SHEETS_WEBHOOK_URL,
        'WEBHOOK_SECRET': WEBHOOK_SECRET,
        'BALE_BOT_TOKEN': BALE_BOT_TOKEN,
        'BALE_CHAT_ID': BALE_CHAT_ID,
    }
    missing = [k for k,v in required.items() if not v]
    if missing:
        fail('Missing secrets: ' + ', '.join(missing))

def resolve_stream_url(url):
    if 'youtube.com' not in url.lower() and 'youtu.be' not in url.lower():
        return url
    for attempt in range(1, 6):
        result = subprocess.run(
            ['yt-dlp','--no-playlist','-f','bestaudio/best','-g',url],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            urls = [x.strip() for x in result.stdout.splitlines() if x.strip()]
            if urls:
                return urls[0]
        print(result.stderr, file=sys.stderr)
        if attempt < 5:
            time.sleep(15)
    fail('Could not resolve live stream.')

def capture_audio(media_url):
    print('Starting immediate one-hour test...')
    result = subprocess.run([
        'ffmpeg','-y','-hide_banner','-loglevel','warning',
        '-reconnect','1','-reconnect_streamed','1','-reconnect_delay_max','5',
        '-i',media_url,'-t',str(CAPTURE_SECONDS),'-vn','-ac','1','-ar','16000',
        '-c:a','libmp3lame','-b:a','32k',str(AUDIO_FILE)
    ], check=False)
    if result.returncode != 0:
        fail('FFmpeg failed.')
    if not AUDIO_FILE.exists() or AUDIO_FILE.stat().st_size < 5000:
        fail('Audio file missing or too small.')
    print('Audio capture completed.')

def transcribe(client):
    uploaded = client.files.upload(file=str(AUDIO_FILE))
    interaction = client.interactions.create(
        model='gemini-3.5-transcribe',
        input=[{'type':'audio','uri':uploaded.uri,'mime_type':uploaded.mime_type}],
        generation_config={
            'transcription_config': {
                'language_codes':['fa-IR'],
                'custom_vocabulary':CUSTOM_VOCABULARY,
                'mode':'smart'
            }
        }
    )
    text = (interaction.output_text or '').strip()
    if not text:
        fail('Empty transcription.')
    TRANSCRIPT_FILE.write_text(text, encoding='utf-8')
    print(f'Transcript saved: {len(text)} characters')
    return text

def analyze(client, transcript):
    prompt = f'''این متن مربوط به یک تست یک‌ساعته از پخش زنده شبکه جهانی ولایت است.

گزارش را صرفاً بر اساس همین متن تولید کن.
قواعد:
1. نام کارشناس را فقط اگر از متن روشن است استخراج کن؛ وگرنه «نامشخص».
2. موضوع اصلی را دقیق و کوتاه بنویس.
3. خلاصه محتوایی جامع از کل بازه تهیه کن، با تمرکز بر محتوای علمی و پاسخ‌ها.
4. محورهای اصلی بحث را استخراج کن.
5. فقط سؤال‌های واقعی مخاطبان را که کارشناس پاسخ داده استخراج کن.
6. سؤال مجری را سؤال مخاطب حساب نکن.
7. phone=تماس تلفنی روشن، message=پیام/پیامک روشن، unknown=نوع ارتباط نامشخص.
8. نام مخاطب فقط اگر صریحاً گفته شده؛ وگرنه «نامشخص».
9. برای هر سؤال، خلاصه پاسخ کارشناس را نیز بنویس.
10. بخش مستقلی با عنوان شبهات نساز.

متن:
----------------
{transcript}
----------------
'''
    errors = []
    for model in ANALYSIS_MODELS:
        for attempt, delay in [(1,15),(2,30),(3,60)]:
            try:
                print(f'Analysis: {model}, attempt {attempt}')
                interaction = client.interactions.create(
                    model=model,
                    input=prompt,
                    response_format={
                        'type':'text',
                        'mime_type':'application/json',
                        'schema':ProgramAnalysis.model_json_schema(),
                    },
                )
                raw = (interaction.output_text or '').strip()
                return ProgramAnalysis.model_validate_json(raw), model
            except Exception as exc:
                errors.append(f'{model}/{attempt}: {exc}')
                print(errors[-1], file=sys.stderr)
                if attempt < 3:
                    time.sleep(delay)
    fail('All Gemini analysis attempts failed. Transcript is preserved.\n' + '\n'.join(errors[-6:]))

def jalali_now():
    now = datetime.now(TEHRAN)
    j = jdatetime.date.fromgregorian(date=now.date())
    return f'{j.year:04d}/{j.month:02d}/{j.day:02d}'

def stats(analysis):
    phone = sum(q.source_type == 'phone' for q in analysis.audience_questions)
    message = sum(q.source_type == 'message' for q in analysis.audience_questions)
    unknown = sum(q.source_type == 'unknown' for q in analysis.audience_questions)
    names = []
    for q in analysis.audience_questions:
        if q.audience_name != 'نامشخص' and q.audience_name not in names:
            names.append(q.audience_name)
    return phone, message, unknown, names

def post_json(url, payload, timeout=45):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type':'application/json; charset=utf-8'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))

def send_to_sheet(analysis, used_model):
    phone, message, unknown, names = stats(analysis)
    report_id = f'ONE_HOUR_TEST_{GITHUB_RUN_ID}'
    payload = {
        'secret':WEBHOOK_SECRET,
        'report_id':report_id,
        'date':jalali_now(),
        'day':'آزمایشی',
        'start':'تست فوری',
        'end':'حدود یک ساعت بعد',
        'program':'تست یک‌ساعته سامانه',
        'expert':analysis.expert,
        'topic':analysis.topic,
        'summary':analysis.summary,
        'key_points':analysis.key_points,
        'phone_question_count':phone,
        'message_question_count':message,
        'unknown_question_count':unknown,
        'total_question_count':len(analysis.audience_questions),
        'audience_names':names,
        'questions':[q.question for q in analysis.audience_questions],
        'answered_questions':[
            {
                'source_type':q.source_type,
                'audience_name':q.audience_name,
                'question':q.question,
                'answer_summary':q.answer_summary,
            }
            for q in analysis.audience_questions
        ],
        'bot_status':'PENDING',
        'status':'TEST_ONE_HOUR',
        'analysis_model':used_model,
    }
    REPORT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    result = post_json(SHEETS_WEBHOOK_URL, payload)
    if result.get('ok') is not True:
        fail('Google Sheet rejected report: ' + str(result))
    return report_id, phone, message, unknown

def send_bale(analysis, report_id, phone, message, unknown):
    url = f'https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage'
    lines = [
        '🧪 گزارش تست یک‌ساعته سامانه دیدبان ولایت','',
        f'🗓 تاریخ: {jalali_now()}',
        f'👤 کارشناس: {analysis.expert}',
        f'🎯 موضوع: {analysis.topic}','',
        '📝 خلاصه محتوایی:',analysis.summary,'',
        '🔹 محورهای اصلی:'
    ]
    for i,item in enumerate(analysis.key_points,1):
        lines.append(f'{i}. {item}')
    lines += [
        '','📊 آمار مخاطبان:',
        f'☎️ تلفنی: {phone}',
        f'💬 پیام/پیامک: {message}',
        f'❔ نوع نامشخص: {unknown}',
        f'✅ مجموع سؤالات پاسخ‌داده‌شده: {len(analysis.audience_questions)}'
    ]
    if analysis.audience_questions:
        lines += ['','❓ سؤال‌های مخاطبان و خلاصه پاسخ:']
        for i,q in enumerate(analysis.audience_questions,1):
            lines.append(f'{i}. {q.question}')
            lines.append(f'↳ پاسخ: {q.answer_summary}')
    text = '\n'.join(lines)
    chunks = []
    while text:
        if len(text) <= 3900:
            chunks.append(text)
            break
        cut = text.rfind('\n',0,3900)
        if cut < 1000:
            cut = 3900
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    for chunk in chunks:
        result = post_json(url, {'chat_id':BALE_CHAT_ID,'text':chunk}, timeout=30)
        if result.get('ok') is not True:
            fail('Bale rejected message: ' + str(result))
        time.sleep(1)
    try:
        post_json(SHEETS_WEBHOOK_URL, {
            'secret':WEBHOOK_SECRET,
            'report_id':report_id,
            'update_only':True,
            'bot_status':'TEST_SENT'
        }, timeout=30)
    except Exception:
        pass

def send_error(msg):
    try:
        url = f'https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage'
        post_json(url, {
            'chat_id':BALE_CHAT_ID,
            'text':'⚠️ خطای تست یک‌ساعته دیدبان ولایت\n\n' + str(msg)[:3300]
        }, timeout=20)
    except Exception:
        pass

def main():
    check_secrets()
    media_url = resolve_stream_url(STREAM_URL)
    capture_audio(media_url)
    client = genai.Client(api_key=GEMINI_API_KEY)
    transcript = transcribe(client)
    analysis, model = analyze(client, transcript)
    report_id, phone, message, unknown = send_to_sheet(analysis, model)
    send_bale(analysis, report_id, phone, message, unknown)
    print('✅ ONE HOUR END-TO-END TEST SUCCESSFUL')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'FATAL: {exc}', file=sys.stderr)
        send_error(exc)
        raise
