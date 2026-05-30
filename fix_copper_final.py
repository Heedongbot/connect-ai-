"""Copper 포스트: base64 롤백 + PMID 유지"""
import pickle, io, sys, re, html as html_lib
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE_DIR = Path(__file__).parent
BLOG_ID   = "2812259517039331714"
COPPER_ID = "653447465802015470"

IMGUR_URLS = [
    "https://i.imgur.com/T85vuL2.png",
    "https://i.imgur.com/391XfdA.jpeg",
]

def get_service():
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
    with open(BASE_DIR / "token.pickle", "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

svc = get_service()
post = svc.posts().get(blogId=BLOG_ID, postId=COPPER_ID).execute()
html = post.get("content", "")
title = post.get("title", "")
raw_labels = post.get("labels", [])
labels = [l if isinstance(l, str) else l.get("name", "") for l in raw_labels]

print(f"현재 길이: {len(html)}")

# base64 data URL → Imgur URL 복원
for url in IMGUR_URLS:
    ext = url.split('.')[-1].lower()
    mime = "image/jpeg" if ext in ("jpg","jpeg") else "image/png"
    pattern = rf'src="data:{re.escape(mime)};base64,[^"]*"'
    if re.search(pattern, html):
        html = re.sub(pattern, f'src="{url}"', html, count=1)
        print(f"복원: {url}")

print(f"복원 후 길이: {len(html)}")

# PMID 현황 재확인
pmids = re.findall(r'PMID\s*\d+', html, re.IGNORECASE)
print(f"PMID: {pmids}")

html = html_lib.unescape(html)
svc.posts().update(blogId=BLOG_ID, postId=COPPER_ID,
                   body={"title": title, "content": html, "labels": labels},
                   publish=False).execute()
print("완료!")
