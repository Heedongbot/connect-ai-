"""라벨 없는 최근 포스팅 라벨 추가"""
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID = "2812259517039331714"

# 라벨 없는 포스팅과 적용할 라벨
FIXES = [
    {
        "url_path": "/2026/05/what-changed-when-i-started-taking-nmn.html",
        "labels": ["NMN", "NAD", "Longevity", "BrainHealth", "AntiAging",
                   "Mitochondria", "Supplements", "NordicHealth", "NutriStackLab"],
    },
    {
        "url_path": "/2026/05/how-i-use-supplement-effectively-my.html",
        "labels": ["Supplements", "NordicHealth", "NutriStackLab", "PersonalProtocol"],
    },
]

def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

def main():
    svc = get_service()
    for fix in FIXES:
        path   = fix["url_path"]
        labels = fix["labels"]
        try:
            post    = svc.posts().getByPath(blogId=BLOG_ID, path=path).execute()
            post_id = post["id"]
            title   = post["title"]
            content = post.get("content", "")
            existing = post.get("labels", [])
            if existing:
                print(f"[이미 있음] {title[:50]} → {existing}")
                continue
            svc.posts().update(
                blogId=BLOG_ID, postId=post_id,
                body={"id": post_id, "title": title, "content": content, "labels": labels}
            ).execute()
            print(f"[OK] {title[:50]}")
            print(f"     라벨: {', '.join(labels)}")
        except Exception as e:
            print(f"[FAIL] {path} → {e}")

if __name__ == "__main__":
    main()
