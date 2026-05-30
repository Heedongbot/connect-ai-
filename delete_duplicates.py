"""오늘/어제 중복 발행된 포스트 삭제"""
import pickle, sys
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID    = "2812259517039331714"

# 삭제할 중복 URL (원본 제외한 것들)
DUPLICATES = [
    # Zinc 중복 3개 (09:03 원본 유지, 13:26/13:39/13:51 삭제)
    "https://www.nutristacklab.com/2026/05/how-i-use-zinc-effectively-my-findings_01859153024.html",
    "https://www.nutristacklab.com/2026/05/how-i-use-zinc-effectively-my-findings_01251767866.html",
    "https://www.nutristacklab.com/2026/05/how-i-use-zinc-effectively-my-findings_01944655654.html",
    # Resveratrol 중복 1개
    "https://www.nutristacklab.com/2026/05/how-i-use-resveratrol-effectively-my_02071055.html",
]

def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

def url_to_post_id(svc, url):
    try:
        res = svc.posts().getByPath(blogId=BLOG_ID, path=url.split("nutristacklab.com")[1]).execute()
        return res.get("id")
    except Exception as e:
        print(f"  ❌ URL 조회 실패: {e}")
        return None

def main():
    svc = get_service()
    for url in DUPLICATES:
        print(f"\n>> {url.split('/')[-1]}")
        pid = url_to_post_id(svc, url)
        if not pid:
            print("  [SKIP] post ID not found (already deleted or wrong URL)")
            continue
        try:
            svc.posts().delete(blogId=BLOG_ID, postId=pid).execute()
            print(f"  [OK] deleted (ID: {pid})")
        except Exception as e:
            print(f"  [FAIL] {e}")

if __name__ == "__main__":
    main()
