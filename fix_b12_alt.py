import pickle, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from googleapiclient.discovery import build

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
svc = build("blogger", "v3", credentials=creds)

BLOG_ID = "2812259517039331714"
POST_ID = "2544187975810617855"

post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
html = post.get("content", "")

# F2: alt에 vitamin b12 키워드 추가
old = 'alt="my B12 bottle next to breakfast"'
new = 'alt="my vitamin B12 bottle next to breakfast"'
fixed = html.replace(old, new)

n = html.count(old)
print(f"교체 대상: {n}곳")

resp = svc.posts().patch(blogId=BLOG_ID, postId=POST_ID,
                         body={"content": fixed}).execute()
print("OK:", resp.get("title"))
