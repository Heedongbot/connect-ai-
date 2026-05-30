"""시트룰린 포스트 단독 발행후 검사"""
import sys, io, logging, pickle, re, os
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

os.chdir(Path(__file__).parent)

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from post_publish_verifier import verify_and_patch, build_discord_report

BLOG_ID  = "2812259517039331714"
POST_ID  = "4659281487730479280"
META_DIR = Path(__file__).parent / "20_Meta"

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("blogger", "v3", credentials=creds)

post      = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title     = post.get("title", "")
html      = post.get("content", "")
og_m      = re.search(r'property="og:description"[^>]*content="([^"]+)"', html, re.I)
og_m      = og_m or re.search(r'og:description.*?content="([^"]+)"', html, re.I | re.DOTALL)
meta_desc = og_m.group(1) if og_m else ""

print(f"title: {title}")
print(f"html length: {len(html)}")
print(f"meta_desc: {meta_desc[:100]}")
print("---")

result = verify_and_patch(
    svc=svc, blog_id=BLOG_ID, post_id=POST_ID,
    title=title, html=html, meta_desc=meta_desc,
    ask_ai_fn=None, ask_ai_fn_claude=None,
    meta_dir=META_DIR,
)
report = build_discord_report(title, result)
print(report)
