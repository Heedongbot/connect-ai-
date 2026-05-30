import pickle, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from googleapiclient.discovery import build
from pathlib import Path

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
svc = build("blogger", "v3", credentials=creds)

html = Path("vitd3_current.html").read_text(encoding="utf-8")
resp = svc.posts().patch(
    blogId="2812259517039331714",
    postId="3917973639242515786",
    body={"title": "The Vitamin D Mistake That Kept Me Tired", "content": html}
).execute()
print("OK:", resp.get("title"))
print("URL:", resp.get("url"))
