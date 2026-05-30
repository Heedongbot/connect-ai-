"""두 오늘 발행된 K2 포스트의 이미지 URL 확인"""
import pickle, re
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_IDS   = {
    "K2 포스트 1 (17:41)": "1445361037999783114",
    "K2 포스트 2 (18:08)": "7619540800960348092",
}

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("blogger", "v3", credentials=creds)

for label, post_id in POST_IDS.items():
    print(f"\n{'='*60}")
    print(f"{label} (post_id={post_id})")
    post = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
    html = post.get("content", "")
    imgs = re.findall(r'src="([^"]+)"', html)
    if not imgs:
        print("  ⚠️ 이미지 없음!")
    for i, url in enumerate(imgs, 1):
        kind = "BASE64" if url.startswith("data:") else ("PLACEHOLDER" if "UPLOAD" in url else "URL")
        display = url[:80] + "..." if len(url) > 80 else url
        print(f"  [{i}] {kind}: {display}")
