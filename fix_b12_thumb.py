import pickle, re
from pathlib import Path
from urllib.parse import quote
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
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID, fields="id,content").execute()
html = post.get("content", "")

if "image.pollinations.ai" in html:
    print("이미 Pollinations img 있음 - 스킵")
else:
    desc = "vitamin B12 cobalamin supplement capsule beside a glass of water and leafy greens, morning kitchen counter"
    thumb_url = "https://image.pollinations.ai/prompt/" + quote(desc) + "?width=800&height=600&nologo=true"
    hidden = '<img src="' + thumb_url + '" style="display:none;width:1px;height:1px;" alt="" />\n'
    svc.posts().update(blogId=BLOG_ID, postId=POST_ID, body={"content": hidden + html}).execute()
    print("완료! Pollinations 썸네일 img 삽입됨")
