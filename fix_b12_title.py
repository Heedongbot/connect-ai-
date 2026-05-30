import pickle
from pathlib import Path
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

with open(Path(__file__).parent / "token.pickle", "rb") as f:
    creds = pickle.load(f)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

svc = build("blogger", "v3", credentials=creds)
BLOG_ID = "2812259517039331714"
POST_ID = "7123665939022173318"

TITLE = "What Changed When I Started Taking Vitamin B12 the Right Way"

result = svc.posts().patch(
    blogId=BLOG_ID, postId=POST_ID,
    body={
        "title": TITLE,
        "searchDescription": "The complete Vitamin B12 (Cobalamin) guide: how it works, best combinations, what to avoid, and my personal protocol after months of testing.",
    }
).execute()

print("제목:", result.get("title"))
print("상태:", result.get("status"))
print("라벨:", result.get("labels"))
