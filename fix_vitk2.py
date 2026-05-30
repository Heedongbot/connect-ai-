"""
Vitamin K2 MK-7 포스팅 7가지 수정
post_id: 1680339452243943318
"""
import re, json, pickle, html as html_lib
from pathlib import Path
from googleapiclient.discovery import build

POST_ID  = "1680339452243943318"
BLOG_ID  = "2812259517039331714"
BASE     = Path(__file__).parent

# ── Blogger 인증 ──────────────────────────────────────────────────
def _get_service():
    token = BASE / "token.pickle"
    with open(token, "rb") as f:
        creds = pickle.load(f)
    from google.auth.transport.requests import Request
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

svc = _get_service()

# ── 현재 포스트 가져오기 ──────────────────────────────────────────
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title   = post["title"]
content = html_lib.unescape(post.get("content", ""))
print(f"[현재 제목] {title}")
print(f"[콘텐츠 길이] {len(content):,}자")

# ================================================================
# Fix 1: 제목 수정 "Is Vitamin K2 Worth Taking? What the Research Says"
# ================================================================
new_title = "Why Vitamin K2 MK-7 Felt Useless Until I Changed the Timing"
print(f"\n[Fix 1] 제목: {title} → {new_title}")

# ================================================================
# Fix 2: Alt 텍스트 수정 — "guide weeks 1–2: what i expected vs. reality" 패턴
# ================================================================
def fix_alts(html):
    # "vitamin k2 mk 7 guide weeks ..." 패턴
    html = re.sub(
        r'alt="[^"]*guide\s+weeks?\s*1[^"]*"',
        'alt="my notes from the first two weeks"',
        html, flags=re.IGNORECASE
    )
    # "What I Expected vs. Reality" 패턴
    html = re.sub(
        r'alt="[^"]*expected\s+vs\.?\s*reality[^"]*"',
        'alt="the bottle I almost stopped using"',
        html, flags=re.IGNORECASE
    )
    # "Guide" + "weeks" 조합 alt
    html = re.sub(
        r'alt="[^"]*k2[^"]*guide[^"]*"',
        'alt="my vitamin k2 bottle from the first month"',
        html, flags=re.IGNORECASE
    )
    return html

# ================================================================
# Fix 3: 캡션 수정 — "Here's what I found: on Weeks 1–2..."
# ================================================================
def fix_captions(html):
    html = re.sub(
        r"Here'?s what I found:\s*on\s+Weeks?\s*1[^<.]*\.\s*",
        "My notes from the first two weeks. ",
        html, flags=re.IGNORECASE
    )
    html = re.sub(
        r"Here'?s what I found:\s*on\s+[^<.]*vs\.?\s*Reality[^<.]*\.\s*",
        "My notes from the first two weeks. ",
        html, flags=re.IGNORECASE
    )
    return html

# ================================================================
# Fix 4: 문법 오류 — "Maybe It", "that's why It", "why It" 대문자 I → 소문자 i
# ================================================================
def fix_grammar(html):
    # "Maybe It wasn't" → "Maybe it wasn't"
    html = re.sub(r'\bMaybe It\b', 'Maybe it', html)
    html = re.sub(r"that'?s why It\b", "that's why it", html, flags=re.IGNORECASE)
    html = re.sub(r'\bwhy It\b', 'why it', html)
    html = re.sub(r'\bthat It\b', 'that it', html)
    html = re.sub(r'\bbut It\b', 'but it', html)
    html = re.sub(r'\band It\b', 'and it', html)
    return html

# ================================================================
# Fix 5: FAQ 소문자 시작 수정 — "patience and tracking"
# ================================================================
def fix_faq_case(html):
    # <dt> 또는 <dd> 내부에서 소문자로 시작하는 첫 단어
    def cap_answer(m):
        inner = m.group(1)
        inner = inner[0].upper() + inner[1:]
        return f'<dd>{inner}</dd>'
    html = re.sub(r'<dd>([a-z])', lambda m: f'<dd>{m.group(1).upper()}', html)
    # "patience and tracking symptoms are recommended" 직접 수정
    html = html.replace(
        "patience and tracking symptoms are recommended",
        "Patience and tracking symptoms are recommended"
    )
    return html

# ================================================================
# Fix 6: 용량 단위 — K2 맥락에서 잘못된 mg 수정 (100mg→100mcg 등)
# ================================================================
def fix_k2_units(html):
    # K2는 마이크로그램(mcg/μg) 단위 — "100mg", "50mg", "150mg"를 mcg로
    # 단, "magnesium 400mg" 같은 다른 영양소 언급은 건드리지 않음
    # "vitamin k2 ... 100mg" 패턴만 대상
    html = re.sub(
        r'(\bVitamin K2[^.]{0,80}?)(\b100\s*mg\b)',
        r'\g<1>100 mcg', html, flags=re.IGNORECASE
    )
    html = re.sub(
        r'(\bVitamin K2[^.]{0,80}?)(\b50\s*mg\b)',
        r'\g<1>50 mcg', html, flags=re.IGNORECASE
    )
    html = re.sub(
        r'(\bVitamin K2[^.]{0,80}?)(\b150\s*mg\b)',
        r'\g<1>150 mcg', html, flags=re.IGNORECASE
    )
    # "100mg" 단독으로 K2 관련 문장에서 나오는 경우
    html = re.sub(r'\btook\s+100\s*mg\b', 'took 100 mcg', html, flags=re.IGNORECASE)
    html = re.sub(r'\bstarted\s+with\s+100\s*mg\b', 'started with 100 mcg', html, flags=re.IGNORECASE)
    return html

# ================================================================
# Fix 7: "What I'd Do Differently" — I'd 반복 15회 → 6~8개로 압축
# ================================================================
def fix_id_section(html):
    # "I'd" 로 시작하는 <li> 항목들 찾기
    section_match = re.search(
        r'(<h2[^>]*>[^<]*[Dd]ifferently[^<]*</h2>)(.*?)(<h2|$)',
        html, re.DOTALL
    )
    if not section_match:
        print("[Fix 7] 'Differently' 섹션 못 찾음 — 스킵")
        return html

    section_html = section_match.group(2)
    li_items = re.findall(r"<li>(I’?d[^<]+)</li>", section_html, re.IGNORECASE)
    if not li_items:
        li_items = re.findall(r"<li>([^<]*I.d\s[^<]+)</li>", section_html, re.IGNORECASE)
    print(f"[Fix 7] 'I'd' 항목 {len(li_items)}개 발견")

    if len(li_items) <= 8:
        print("[Fix 7] 8개 이하 - 수정 불필요")
        return html

    # 앞에서 6개만 유지 (가장 핵심적인 것들)
    kept = li_items[:6]
    new_list = "\n".join(f"<li>{item}</li>" for item in kept)

    # 섹션 내 전체 <ul> 블록 교체
    old_ul = re.search(r'<ul>[\s\S]*?</ul>', section_html)
    if old_ul:
        new_ul = f"<ul>\n{new_list}\n</ul>"
        html = html.replace(old_ul.group(0), new_ul, 1)
    print(f"[Fix 7] {len(li_items)}개 → 6개로 압축 완료")
    return html

# ================================================================
# Fix 8: 효과 과잉 — 7가지 개선 중 관절/혈압 외 3가지 제거
# ================================================================
def fix_benefits_overload(html):
    # "수면", "기분", "소화", "피부", "치아" 개선 언급 중 과도한 것 제거
    # "improved sleep", "better mood", "improved digestion" 패턴
    overstatements = [
        (r'<li>[^<]*\b(sleep|mood)\b[^<]*(improved|better|quality)[^<]*</li>', ''),
        (r'<li>[^<]*(improved|better)\b[^<]*\b(sleep|mood)\b[^<]*</li>', ''),
        (r'<li>[^<]*\b(skin|teeth|dental)\b[^<]*(improved|better|clearer|stronger)[^<]*</li>', ''),
        (r'<li>[^<]*(improved|better)\b[^<]*\b(skin|teeth|dental)\b[^<]*</li>', ''),
    ]
    removed = 0
    for pattern, repl in overstatements:
        new_html, n = re.subn(pattern, repl, html, flags=re.IGNORECASE)
        if n > 0:
            html = new_html
            removed += n
    print(f"[Fix 8] 과잉 효과 항목 {removed}개 제거")
    return html

# ================================================================
# og:title, og:description, JSON-LD headline 동기화
# ================================================================
def fix_meta_title(html, new_t):
    html = re.sub(r'<meta property="og:title"[^/]*/>', f'<meta property="og:title" content="{new_t}"/>', html)
    html = re.sub(r'"headline"\s*:\s*"[^"]+"', f'"headline": "{new_t}"', html)
    # Blogger title 태그
    html = re.sub(r'<title>[^<]+</title>', f'<title>{new_t}</title>', html)
    return html

# ── 모든 Fix 적용 ─────────────────────────────────────────────────
content = fix_alts(content)
content = fix_captions(content)
content = fix_grammar(content)
content = fix_faq_case(content)
content = fix_k2_units(content)
content = fix_id_section(content)
content = fix_benefits_overload(content)
content = fix_meta_title(content, new_title)

# ── Blogger 업데이트 ──────────────────────────────────────────────
print("\n[업데이트] Blogger 패치 중...")
svc.posts().update(
    blogId=BLOG_ID, postId=POST_ID,
    body={"title": new_title, "content": html_lib.unescape(content)},
    publish=False
).execute()
print(f"✅ 완료! 제목: {new_title}")

# ── published_links.json 제목 동기화 ─────────────────────────────
links_file = BASE / "20_Meta" / "published_links.json"
links = json.loads(links_file.read_text(encoding="utf-8"))
for lnk in links:
    if lnk.get("post_id") == POST_ID:
        lnk["title"] = new_title
        break
links_file.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
print("✅ published_links.json 제목 동기화 완료")
