import pickle, html as html_lib, re
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
content = html_lib.unescape(post.get("content", ""))

# alt 패턴
alts = re.findall(r'alt="([^"]{10,})"', content)
print("=== ALT 텍스트 ===")
for a in alts: print(" ", a)

# 캡션
captions = re.findall(r'<figcaption[^>]*>([^<]+)<', content)
print("\n=== 캡션 ===")
for c in captions: print(" ", c)

# It 대문자
it_hits = re.findall(r'.{30} It .{30}', content)
print("\n=== 'It' 대문자 패턴 ===")
for h in it_hits[:5]: print(" ", h)

# FAQ 소문자 시작
dd_hits = re.findall(r'<dd>([a-z][^<]{10,})', content)
print("\n=== FAQ 소문자 시작 ===")
for h in dd_hits[:5]: print(" ", h[:80])

# I'd 패턴
id_hits = re.findall(r"<li>([^<]*[Ii][’']d[^<]+)</li>", content)
print(f"\n=== I'd 패턴 ({len(id_hits)}개) ===")
for h in id_hits[:5]: print(" ", h[:80])

# 용량
mg_hits = re.findall(r'.{20}\d+\s*mg.{20}', content)
print("\n=== mg 단위 ===")
for h in mg_hits[:5]: print(" ", h)

# 효과 (관절,혈압,피부,소화,치아,수면,기분)
keywords = ["joint", "blood pressure", "skin", "digestion", "teeth", "sleep", "mood"]
print("\n=== 효과 키워드 ===")
for kw in keywords:
    hits = re.findall(rf'.{{0,40}}{kw}.{{0,40}}', content, re.IGNORECASE)
    if hits:
        print(f"  [{kw}] {hits[0][:80]}")
