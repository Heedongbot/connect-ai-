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

# sleep <li> 제거
content, n1 = re.subn(
    r'<li>[^<]*smoother transition into sleep[^<]*</li>',
    '', content, flags=re.IGNORECASE
)
print(f"sleep <li> 제거: {n1}건")

# "didn't notice any dramatic shifts in my mood" 문장이 있는 <p> 제거
content, n2 = re.subn(
    r"<p>[^<]*didn.t notice any dramatic shifts in my mood[^<]*</p>",
    '', content, flags=re.IGNORECASE
)
print(f"mood <p> 제거: {n2}건")

total = n1 + n2
if total:
    svc.posts().update(
        blogId=BLOG_ID, postId=POST_ID,
        body={"title": title, "content": html_lib.unescape(content)},
        publish=False
    ).execute()
    print("업데이트 완료")
else:
    print("변경 없음")

# 최종 확인
print("\n=== 최종 효과 키워드 ===")
for kw in ["joint","blood pressure","skin","digestion","teeth","sleep","mood"]:
    cnt = len(re.findall(rf'\b{kw}\b', content, re.IGNORECASE))
    print(f"  {kw}: {cnt}회")
print(f"\n제목: {title}")
print(f"길이: {len(content):,}자")
