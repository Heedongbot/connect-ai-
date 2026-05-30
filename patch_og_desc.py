import json, pickle, re
from pathlib import Path
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

TOKEN_FILE = Path(__file__).parent / "token.pickle"
with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

svc = build("blogger", "v3", credentials=creds)
BLOG_ID = "2812259517039331714"
POST_ID = "6521023620032722085"  # Citrulline Malate

# completed 폴더에서 meta_desc 추출
comp = Path(__file__).parent / "03_Completed"
files = sorted(comp.glob("*Citrulline*"), key=lambda f: f.stat().st_mtime, reverse=True)
desc = ""
if files:
    html = files[0].read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"description":"([^"]+)"', html)
    if m:
        desc = m.group(1)
        print("JSON-LD에서 추출:", desc[:100])

if not desc:
    desc = "The complete Citrulline Malate guide: how it works, best combinations, timing, and my personal protocol after testing."
    print("폴백 사용:", desc[:100])

result = svc.posts().patch(
    blogId=BLOG_ID, postId=POST_ID,
    body={"searchDescription": desc[:150]}
).execute()
print("패치 완료!")
print("URL:", result.get("url", ""))
