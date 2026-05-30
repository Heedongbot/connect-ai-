import pickle, re
from pathlib import Path
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

BLOG_ID   = "2812259517039331714"
POST_ID   = "7123665939022173318"
TOKEN_FILE = Path(__file__).parent / "token.pickle"

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

svc  = build("blogger", "v3", credentials=creds)
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID, fields="id,title,content").execute()

print("=== Blogger 포스트 제목 ===")
print(post.get("title", ""))

html = post.get("content", "")
print("\n=== JSON-LD 블록 ===")
for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL):
    print(m.group(1)[:500])
    print("---")

print("\n=== H1 태그 ===")
h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
if h1:
    print(re.sub(r'<[^>]+>', '', h1.group(1)).strip())
