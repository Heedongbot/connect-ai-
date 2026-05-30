import sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[logging.StreamHandler()])

import pickle, json, requests
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).parent.parent))
from post_publish_verifier import verify_and_patch, build_discord_report

BLOG_ID  = '2812259517039331714'
POST_ID  = '1709045621705465996'
META_DIR = Path(__file__).parent.parent / '20_Meta'

with open('token.pickle', 'rb') as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build('blogger', 'v3', credentials=creds)

post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title   = post['title']
html    = post['content']

# ── 1차 스캔: local Ollama (빠르고 무료)
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:14b-q4_K_M"

def ask_ai_local(prompt, system=""):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system or "You are a helpful assistant.",
            "stream": False,
            "options": {"temperature": 0.4},
        }, timeout=300)
        return r.json().get('response', '').strip()
    except Exception as e:
        logging.warning(f"[Local Ollama 실패] {e} — Claude API 폴백")
        return ask_ai_claude(prompt, system)

# ── 2차 스캔: Claude API (정밀 검증)
import anthropic
from pathlib import Path as _Path

def _get_api_key():
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env_path = _Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

_api_key = _get_api_key()
if not _api_key:
    print("[오류] ANTHROPIC_API_KEY를 찾을 수 없습니다.")
    sys.exit(1)

_client = anthropic.Anthropic(api_key=_api_key)

def ask_ai_claude(prompt, system=""):
    msg = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=system or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

result = verify_and_patch(
    svc=svc, blog_id=BLOG_ID, post_id=POST_ID,
    title=title, html=html, meta_desc="",
    ask_ai_fn=ask_ai_local,
    ask_ai_fn_claude=ask_ai_claude,
    meta_dir=META_DIR,
)

report = build_discord_report(title, result)
print(report)
print()
print(f"scan1={result['scan1_count']} scan2={result['scan2_count']} clean={result['scan2_clean']}")
