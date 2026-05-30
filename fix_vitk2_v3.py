"""sleep/mood 잔여 문장 처리 + 최종 검증"""
import re, pickle, html as html_lib
from pathlib import Path
from googleapiclient.discovery import build

POST_ID = "1680339452243943318"
BLOG_ID = "2812259517039331714"
BASE    = Path(__file__).parent

def _get_service():
    with open(BASE / "token.pickle", "rb") as f:
        creds = pickle.load(f)
    from google.auth.transport.requests import Request
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

svc     = _get_service()
post    = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title   = post["title"]
content = html_lib.unescape(post.get("content", ""))

# sleep 문장 찾기
sleep_hits = re.findall(r'.{0,60}sleep.{0,60}', content, re.IGNORECASE)
print("SLEEP:", [h for h in sleep_hits if "transition" in h or "smoother" in h])

mood_hits = re.findall(r'.{0,60}mood.{0,60}', content, re.IGNORECASE)
print("MOOD:", mood_hits[:3])

# 직접 제거
remove_phrases = [
    r'<p>[^<]{0,200}smoother transition into sleep[^<]{0,200}</p>',
    r'<p>[^<]{0,200}wasn.t about energy or mood[^<]{0,200}</p>',
    r'<p>[^<]{0,200}transition into sleep[^<]{0,200}</p>',
    r'<p>[^<]{0,200}better sleep[^<]{0,200}</p>',
]

changed = False
for pat in remove_phrases:
    new, n = re.subn(pat, '', content, flags=re.IGNORECASE | re.DOTALL)
    if n:
        print(f"제거 {n}건: {pat[:50]}")
        content = new
        changed = True

if changed:
    svc.posts().update(
        blogId=BLOG_ID, postId=POST_ID,
        body={"title": title, "content": html_lib.unescape(content)},
        publish=False
    ).execute()
    print("업데이트 완료")
else:
    print("추가 제거 없음 - 이미 완료됨")

# 최종 효과 키워드 카운트
keywords = ["joint", "blood pressure", "skin", "digestion", "teeth", "sleep", "mood"]
print("\n=== 최종 효과 키워드 ===")
for kw in keywords:
    cnt = len(re.findall(rf'\b{kw}\b', content, re.IGNORECASE))
    print(f"  {kw}: {cnt}회")
