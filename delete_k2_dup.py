"""1번째 K2 중복 포스트 삭제"""
import pickle, json
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
DEL_POST_ID = "1445361037999783114"
LINKS_FILE  = BASE_DIR / "20_Meta" / "published_links.json"

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("blogger", "v3", credentials=creds)

# Blogger 삭제
try:
    svc.posts().delete(blogId=BLOG_ID, postId=DEL_POST_ID).execute()
    print("Blogger delete OK post_id=" + DEL_POST_ID)
except Exception as e:
    print("Blogger delete FAILED: " + str(e))

# published_links.json에서 제거
items = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
before = len(items)
items = [p for p in items if p.get("post_id") != DEL_POST_ID]
LINKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"published_links.json: {before} -> {len(items)}")
