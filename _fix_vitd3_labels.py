"""Vitamin D3 포스트 라벨 추가"""
import sys, io, pickle
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_ID    = "2909644206769826126"

LABELS = [
    "VitaminD3",
    "D3",
    "D3CompleteGuide",
    "NutriStackLabVitaminD3",
    "VitaminD3Guide",
    "BoneHealth",
    "ImmuneSupport",
    "MoodSupport",
    "NordicHealth",
    "NutriStackLab",
    "Supplements",
    "VitaminsAndMinerals",
    "SunshineVitamin",
    "HealthyAging",
]

from google.auth.transport.requests import Request
from googleapiclient.discovery import build as _build

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = _build("blogger", "v3", credentials=creds)

post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
print(f"제목: {post['title']}")
print(f"기존 라벨: {post.get('labels', [])}")

svc.posts().patch(
    blogId=BLOG_ID, postId=POST_ID,
    body={"labels": LABELS}
).execute()

print(f"\n✅ 라벨 {len(LABELS)}개 추가 완료:")
for l in LABELS:
    print(f"  - {l}")
