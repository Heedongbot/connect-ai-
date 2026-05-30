"""최근 포스팅 라벨 확인"""
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID = "2812259517039331714"

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("blogger", "v3", credentials=creds)

posts = svc.posts().list(blogId=BLOG_ID, maxResults=8, orderBy="PUBLISHED").execute()
for p in posts.get("items", []):
    labels = p.get("labels", [])
    pub = p.get("published", "")[:16]
    title = p.get("title", "")[:55]
    label_str = ", ".join(labels) if labels else "없음"
    print(f"{pub} | {title}")
    print(f"  라벨: {label_str}")
