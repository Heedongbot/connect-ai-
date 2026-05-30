"""두 K2 포스트의 이미지 상황 전체 진단"""
import pickle, re
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_IDS   = {
    "K2-1 (17:41)": "1445361037999783114",
    "K2-2 (18:08)": "7619540800960348092",
}

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("blogger", "v3", credentials=creds)

for label, post_id in POST_IDS.items():
    print(f"\n{'='*60}\n{label}")
    post = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
    html = post.get("content", "")

    print(f"  HTML 길이: {len(html):,} bytes")

    # 모든 이미지 패턴 확인
    src_urls   = re.findall(r'src="([^"]+)"', html)
    data_imgs  = re.findall(r'src="(data:image/[^"]{0,60})', html)
    placeholders = re.findall(r'\[UPLOAD[^\]]*\]', html)
    h2_count   = len(re.findall(r'<h2', html, re.IGNORECASE))

    print(f"  H2 섹션 수: {h2_count}")
    print(f"  src= URL 수: {len(src_urls)}")
    for u in src_urls:
        print(f"    {u[:80]}")
    if data_imgs:
        print(f"  Base64 이미지 수: {len(data_imgs)}")
    if placeholders:
        print(f"  Placeholder 수: {len(placeholders)}")
        for p in placeholders:
            print(f"    {p}")
    if not src_urls and not data_imgs and not placeholders:
        print("  ⚠️ 이미지 없음!")
