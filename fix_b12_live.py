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

# 현재 상태 먼저 확인
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID, fields="id,title,status,labels").execute()
print("현재 상태:", post.get("status"))
print("현재 제목:", post.get("title"))

# status LIVE 포함해서 patch
result = svc.posts().patch(
    blogId=BLOG_ID, postId=POST_ID,
    body={
        "title": "What Changed When I Started Taking Vitamin B12 the Right Way",
        "status": "LIVE",
        "labels": ["VitaminB12", "Supplements", "NordicHealth", "NutriStackLab", "CobalaminGuide"],
        "searchDescription": "The complete Vitamin B12 (Cobalamin) guide: how it works, best combinations, what to avoid, and my personal protocol after months of testing.",
    }
).execute()

print("패치 후 상태:", result.get("status"))
print("패치 후 제목:", result.get("title"))
