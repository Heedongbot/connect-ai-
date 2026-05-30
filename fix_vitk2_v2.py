"""
Vitamin K2 K2 MK-7 포스팅 남은 수정
- mg -> mcg
- 효과 7개 -> 2-3개 (joint, blood pressure 유지, 나머지 삭제)
- I'd 반복 압축
"""
import re, json, pickle, html as html_lib
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
print(f"제목: {title} / 길이: {len(content):,}자")

# ================================================================
# Fix A: K2 mg → mcg
# ================================================================
def fix_units(html):
    n = 0
    for pat, rep in [
        (r'\b100\s*mg\b', '100 mcg'),
        (r'\b50\s*mg\b',  '50 mcg'),
        (r'\b150\s*mg\b', '150 mcg'),
    ]:
        new, cnt = re.subn(pat, rep, html, flags=re.IGNORECASE)
        if cnt:
            print(f"  [단위] {pat} -> {rep} ({cnt}건)")
            html = new
            n += cnt
    print(f"  [단위] 총 {n}건 수정")
    return html

# ================================================================
# Fix B: 효과 과잉 — skin/teeth/sleep/mood 문장 제거
# ================================================================
def fix_benefits(html):
    remove_patterns = [
        # skin
        r'<p>[^<]*\bskin\b[^<]*(subtle|improv|chang|glow|clear)[^<]*</p>',
        r'<p>[^<]*(subtle|improv|chang|glow|clear)[^<]*\bskin\b[^<]*</p>',
        # teeth / grinding
        r'<p>[^<]*grinding my teeth[^<]*</p>',
        r'<p>[^<]*\bteeth\b[^<]*(grind|weird|noticed)[^<]*</p>',
        # sleep
        r'<p>[^<]*smoother transition into sleep[^<]*</p>',
        r'<p>[^<]*\bsleep\b[^<]*(smooth|easier|better|improv)[^<]*</p>',
        # mood (standalone sentence)
        r'<p>[^<]*wasn.t about energy or mood[^<]*</p>',
    ]
    removed = 0
    for pat in remove_patterns:
        new, n = re.subn(pat, '', html, flags=re.IGNORECASE | re.DOTALL)
        if n:
            print(f"  [효과삭제] 패턴 {n}건: {pat[:50]}...")
            html = new
            removed += n
    print(f"  [효과삭제] 총 {removed}문장 제거")
    return html

# ================================================================
# Fix C: "I'd" 반복 압축 (Unicode apostrophe 포함)
# ================================================================
def fix_id_repetition(html):
    # 모든 apostrophe 변형 처리
    id_pattern = r"<li>([^<]*I[’‘']d\s[^<]+)</li>"
    all_items = re.findall(id_pattern, html, re.IGNORECASE)
    print(f"  [I'd압축] 발견 {len(all_items)}개")

    if len(all_items) <= 8:
        # <li> 형식이 아닐 경우 <p> 형식 시도
        id_p_pattern = r"<p>([^<]*I[’‘']d\s[^<]+)</p>"
        p_items = re.findall(id_p_pattern, html, re.IGNORECASE)
        print(f"  [I'd압축] <p> 형식 {len(p_items)}개")
        if len(p_items) > 8:
            kept = p_items[:6]
            for item in p_items[6:]:
                html = html.replace(f"<p>{item}</p>", "", 1)
            print(f"  [I'd압축] {len(p_items)} -> 6개로 압축")
        return html

    kept = all_items[:6]
    for item in all_items[6:]:
        html = html.replace(f"<li>{item}</li>", "", 1)
    print(f"  [I'd압축] {len(all_items)} -> 6개로 압축")
    return html

# ── 적용 ─────────────────────────────────────────────────────────
print("\n[Fix A] 단위 수정")
content = fix_units(content)

print("\n[Fix B] 효과 과잉 제거")
content = fix_benefits(content)

print("\n[Fix C] I'd 반복 압축")
content = fix_id_repetition(content)

# ── Blogger 업데이트 ─────────────────────────────────────────────
print("\n[업데이트] Blogger 패치...")
svc.posts().update(
    blogId=BLOG_ID, postId=POST_ID,
    body={"title": title, "content": html_lib.unescape(content)},
    publish=False
).execute()
print("완료!")
