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

# 현재 상태 전체 확인
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
print("제목:", post.get("title", ""))
print("상태:", post.get("status", ""))
print("라벨:", post.get("labels", []))
print("URL:", post.get("url", ""))
print()

# 라벨 복구 + LIVE 발행 상태 확인
labels = post.get("labels", [])
if not labels:
    labels = ["VitaminB12", "Supplements", "NordicHealth", "NutriStackLab", "CobalaminGuide"]
    print("라벨 없음 → 복구:", labels)

# publish로 강제 발행 상태 전환
try:
    result = svc.posts().publish(blogId=BLOG_ID, postId=POST_ID).execute()
    print("publish() 성공:", result.get("status"))
except Exception as e:
    print("publish() 실패 (이미 LIVE?):", e)

# 라벨 패치
result2 = svc.posts().patch(
    blogId=BLOG_ID, postId=POST_ID,
    body={"labels": labels}
).execute()
print("라벨 패치 완료:", result2.get("labels"))
print("최종 상태:", result2.get("status"))
