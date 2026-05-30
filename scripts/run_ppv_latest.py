"""
run_ppv_latest.py — published_links.json 최신 포스팅에 발행후 검증 수동 실행
"""
import sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[logging.StreamHandler()])

import json, pickle, requests
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
from post_publish_verifier import verify_and_patch, build_discord_report

META_DIR = BASE_DIR / '20_Meta'
BLOG_ID  = '2812259517039331714'

# ── 최신 포스팅 로드
links_path = META_DIR / 'published_links.json'
if not links_path.exists():
    print("[오류] published_links.json 없음")
    sys.exit(1)

links = json.loads(links_path.read_text(encoding='utf-8'))
if not links:
    print("[오류] published_links.json 비어 있음")
    sys.exit(1)

latest = links[-1]
POST_ID = latest.get('post_id', '')
if not POST_ID:
    print("[오류] 최신 포스팅에 post_id 없음:", latest)
    sys.exit(1)

print(f"[PPV] 대상: {latest.get('title', '')[:60]}")
print(f"[PPV] post_id: {POST_ID}")
print(f"[PPV] URL: {latest.get('url', '')}")
print()

# ── Blogger API
token_path = BASE_DIR / 'token.pickle'
with open(token_path, 'rb') as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build('blogger', 'v3', credentials=creds)

post  = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title = post['title']
html  = post['content']

# ── 1차 스캔: local Ollama
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

# ── 2차 스캔: Claude API
import anthropic

def _get_api_key():
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env_path = BASE_DIR.parent / ".env"
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

# ── 실행
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
