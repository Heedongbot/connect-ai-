"""Vitamin D3 포스트 — Blogger 목록 썸네일용 hidden img 맨 앞에 주입"""
import sys, io, pickle, re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_ID    = "2909644206769826126"

IMG_URL = (
    "https://image.pollinations.ai/prompt/"
    "vitamin%20D3%20supplement%20capsules%20sunlight%20wooden%20table%20nordic%20natural%20light"
    "?width=800&height=500&nologo=true&seed=42"
)

from google.auth.transport.requests import Request
from googleapiclient.discovery import build as _build

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = _build("blogger", "v3", credentials=creds)

post  = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title = post["title"]
html  = post["content"]

# Blogger 목록 썸네일용 hidden img — HTML 최상단에 삽입
HIDDEN_THUMB = (
    f'<img src="{IMG_URL}" '
    f'style="display:none;width:1px;height:1px;" alt="" />\n'
)

if 'display:none' not in html:
    html = HIDDEN_THUMB + html
    print("✅ 썸네일용 hidden img 삽입 완료")
else:
    print("⏭️  이미 존재")

svc.posts().update(
    blogId=BLOG_ID, postId=POST_ID,
    body={"id": POST_ID, "title": title, "content": html}
).execute()
print("✅ 패치 완료 — 목록 썸네일이 곧 반영됩니다")
