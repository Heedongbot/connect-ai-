"""
post_quality_check.py — NutriStack Lab 포스팅 자동 채점

사용법:
  python post_quality_check.py                          # 오늘 발행/예약 포스트 전체
  python post_quality_check.py --post-id 1234567890    # 특정 포스트
  python post_quality_check.py --scheduled              # 예약된 포스트만
  python post_quality_check.py --all                    # 최근 10개 전체

채점 기준:
  [A] 제목 품질       A1(오염여부) A2(길이/SEO)
  [B] 메타 데이터     B1(og:description) B2(alt태그)
  [C] 콘텐츠 품질     C1(Hook) C2(섹션제목) C3(본문길이) C4(AI패턴) C5(사람느낌) C6(의학용어밀도)
  [D] 기술적 완성도   D1(PMID유효성) D2(내부링크) D3(필수요소) D4(HTML구조)
  [E] 애드센스 가능성 E1(YMYL안전) E2(독창성) E3(브랜드일관)
  [F] 정확성          F1(영양소명 정확성: D3/K2/B12 등 숫자식별자)
"""

import argparse, json, pickle, re, sys, io, os, time
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── 카테고리별 담당 에이전트 라우팅
AGENT_ROUTING = {
    "A1": "04_SEO_Optimizer",       # 제목 오염 → SEO 담당
    "A2": "04_SEO_Optimizer",       # 제목 길이/SEO
    "B1": "04_SEO_Optimizer",       # og:description → SEO 담당
    "B2": "03_Writer_Gardener",     # alt 태그 → Writer 담당
    "C1": "03_Writer_Gardener",     # Hook
    "C2": "03_Writer_Gardener",     # 섹션 제목 (H2)
    "C3": "03_Writer_Gardener",     # 본문 길이
    "C4": "03_Writer_Gardener",     # AI 패턴
    "C5": "03_Writer_Gardener",     # 사람 블로그 느낌
    "C6": "02_Researcher_Synergy",  # 의학 용어 밀도 → Researcher 담당
    "D1": "02_Researcher_Synergy",  # PMID 유효성 → Researcher 담당
    "D2": "04_SEO_Optimizer",       # 내부 링크 → SEO 담당
    "D3": "03_Writer_Gardener",     # 필수 요소 (hook/img/disclosure 등)
    "D4": "04_SEO_Optimizer",       # HTML 구조 → SEO 담당
    "E1": "03_Writer_Gardener",     # YMYL 안전성
    "E2": "03_Writer_Gardener",     # 콘텐츠 독창성
    "E3": "04_SEO_Optimizer",       # 브랜드 일관성
    "F1": "03_Writer_Gardener",     # 영양소명 정확성
    "F2": "03_Writer_Gardener",     # 이미지 유효성/관련성
}

CATEGORY_LABELS = {
    "A1": "제목 오염 여부",
    "A2": "제목 길이/SEO",
    "B1": "og:description 상태",
    "B2": "이미지 alt 태그",
    "C1": "Hook 존재/품질",
    "C2": "H2 섹션 제목",
    "C3": "본문 단어 수",
    "C4": "AI 패턴 제거",
    "C5": "사람 블로그 느낌",
    "C6": "의학 용어 밀도",
    "D1": "PMID/연구링크 유효성",
    "D2": "내부 링크 수",
    "D3": "필수 요소 존재",
    "D4": "HTML 구조 완성도",
    "E1": "YMYL 안전성",
    "E2": "콘텐츠 독창성",
    "E3": "브랜드 일관성",
    "F1": "영양소명 정확성",
    "F2": "이미지 유효성/관련성",
}

HERMES_THRESHOLD = 3   # 동일 실수 N회 이상 → Hermes 에스컬레이션

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
LINKS_FILE        = BASE_DIR / "20_Meta" / "published_links.json"
LESSONS_FILE_PATH = BASE_DIR / "20_Meta" / "agent_lessons.json"
HERMES_QUEUE_PATH = BASE_DIR / "20_Meta" / "hermes_queue.json"

# ── 오염 패턴 정의
BAD_TITLE_PATTERNS = [
    re.compile(r"How I Use \w+ Effectively", re.I),
    re.compile(r"\bEffectively: My Findings\b", re.I),
    re.compile(r"What Changed When I Started Taking .+ the Right Way", re.I),
    re.compile(r"^Morning vs Evening: My Choice After Testing$", re.I),
    re.compile(r"^\w+ vs \w+: My Choice After Testing$", re.I),
    re.compile(r"\bMolecular\b|\bLongevity Engine\b|\bMechanism\b", re.I),
    re.compile(r"Why I Pair Best With", re.I),
    re.compile(r"How I Use .+ Effectively", re.I),
    re.compile(r"Is \w+ Worth Taking\?", re.I),          # "Is NMN Worth Taking?"
    re.compile(r"What the Research Says", re.I),          # 제목 끝에 붙는 클리셰
    re.compile(r"Worth Taking\??\s*What", re.I),          # "Worth Taking? What..."
    re.compile(r"\bDosage Guide\b",        re.I),          # v7.6: 2020년대 SEO 제목 그대로
    re.compile(r"How Much Do You Need",    re.I),          # v7.6: 동일 이유
    re.compile(r":\s*Guide to\s+\w",       re.I),          # v7.6: ": Guide to dosage and benefits" 회귀
    re.compile(r"\band [Bb]enefits$",      re.I),          # v7.6: "Dosage and Benefits" 말미 패턴
    re.compile(r"Benefits,?\s*Dosage,?\s*and Side Effects", re.I),  # v7.9: 전형적 SEO 3종세트
    re.compile(r"\bBenefits and Side Effects\b", re.I),    # v7.9: 변형 패턴
    re.compile(r"Dosage,?\s*Benefits,?\s*and", re.I),      # v7.9: 순서 변형
]
BAD_TITLE_WORDS = ["Molecular", "Longevity", "Effectively", "Mechanism", "Blocks",
                   "Worth Taking", "Research Says", "Dosage Guide",
                   # YMYL 치료/완치 표현 — Google 건강 콘텐츠 정책 위반 위험
                   "Healed My", "Cured My", "Eliminated My", "Fixed My Chronic",
                   "Reversed My", "Defeated My", "Overcame My Chronic"]
# "Complete Guide" / "Complete" 제거 — SEO 키워드로 유효함
# "Is X Worth Taking? What the Research Says" 조합만 차단

AI_PATTERNS = [
    r"\brecommendation medications\b",  # → prescription medications
    "it's worth noting",
    "in conclusion",
    "delve into",
    "it is important to note",
    "furthermore",
    "moreover",
    "as an ai",
    "as a language model",
    "oslo",
    "07:15 am",
    "it's fascinating",
    "plays a crucial role",
    "cutting-edge",
    "game-changer",
    "paradigm shift",
    "as we can see",
    "to summarize",
    "in summary",
    "what actually happened",
    "what actually changed",
    "what actually worked",
    "what actually noticed",
    "real talk:",
    "complete guide",
    "nordic science",
    "miracle molecule",
    "new level of productivity",
    "aging slower",
    "thriving",
    "warzone",
    "battlefield",
    "no exceptions",
    "consistency is everything",
    "consistency is key",
    "consistency is what matters",
    # v7.6: 추가 AI 학술 전환어
    "furthermore",
    "moreover",
    "additionally",
    "it is important to note",
    "it's important to note",
    "it should be noted",
    "needless to say",
    "it goes without saying",
    "as we can see",
    "to summarize",
    "in summary",
    "plays a crucial role",
    "plays a vital role",
    "cutting-edge",
    "state-of-the-art",
    "paradigm shift",
    "groundbreaking",
    "revolutionary",
    "scientifically proven",
    "studies have shown",
    "studies have demonstrated",
    "evidence-based",
    "it's fascinating",
    "let's dive into",
    "let's explore",
    "nordic science",
    "as mentioned above",
    "as mentioned earlier",
    "in this article, we will",
    "by the end of this article",
    "stable afternoon energy",
    "may support-all",
    "routine d3",
    "routine vitamin",
]

MEDICAL_JARGON = [
    "chylomicron", "mechanistically", "endocannabinoid", "phytoconstituent",
    "bioavailability matrix", "immunomodulatory", "hepatoprotective",
    "anti-inflammatory cytokine cascade", "nrf2 pathway",
]

REQUIRED_ELEMENTS = ["hook", "h2", "img", "disclosure", "takeaways"]

BROKEN_TEXT_PATTERNS = [
    r"\[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE\]",
    r"topic_label",
    r"\{nutrient\}",
    r"PLACEHOLDER",
    r"lorem ipsum",
    r"07:15 AM Oslo",
    r"Write ONE SEO",
]


# ── Blogger API
def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def get_posts(svc, post_id=None, scheduled_only=False, max_results=10):
    if post_id:
        try:
            p = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
            return [p]
        except Exception:
            result = svc.posts().list(blogId=BLOG_ID, status=["SCHEDULED","DRAFT"], maxResults=20).execute()
            for p in result.get("items", []):
                if p["id"] == post_id:
                    return [p]
            return []

    posts = []
    if scheduled_only:
        result = svc.posts().list(blogId=BLOG_ID, status=["SCHEDULED"], maxResults=max_results).execute()
        posts = result.get("items", [])
    else:
        r1 = svc.posts().list(blogId=BLOG_ID, status=["LIVE"], maxResults=max_results, orderBy="PUBLISHED").execute()
        r2 = svc.posts().list(blogId=BLOG_ID, status=["SCHEDULED"], maxResults=5).execute()
        posts = r1.get("items", []) + r2.get("items", [])
    return posts


# ── 채점 함수들

def score_A(title: str, html: str) -> dict:
    scores = {}

    # A1. 제목 오염 여부
    a1 = 10
    issues = []
    for p in BAD_TITLE_PATTERNS:
        if p.search(title):
            a1 = 0
            issues.append(f"오염패턴: {p.pattern[:40]}")
    if any(w.lower() in title.lower() for w in BAD_TITLE_WORDS):
        a1 = min(a1, 3)
        issues.append(f"오염단어 포함")
    broken = [p for p in BROKEN_TEXT_PATTERNS if re.search(p, title, re.I)]
    if broken:
        a1 = 0
        issues.append("깨진텍스트")
    scores["A1"] = (a1, ", ".join(issues) if issues else "OK")

    # A2. 제목 길이/SEO
    tlen = len(title)
    if 40 <= tlen <= 65:
        a2, note = 10, f"{tlen}자 적정"
    elif 30 <= tlen < 40 or 65 < tlen <= 80:
        a2, note = 7, f"{tlen}자 (권장 40-65)"
    else:
        a2, note = 3, f"{tlen}자 너무 {'짧음' if tlen < 30 else '김'}"
    # 영양소명 포함 여부
    nutrient_words = re.findall(
        r'\b(Vitamin [A-Z]\d*|CoQ10|NMN|Magnesium|Zinc|Elderberry|B12|K2|Citrulline|Omega|'
        r'Selenium|Quercetin|Melatonin|Glycine|Resveratrol|Biotin|Probiotics?|Probiotic|'
        r'Berberine|Iron|Creatine|HMB|Ashwagandha|Collagen|Turmeric|Curcumin|'
        r'Alpha.GPC|CDP.Choline|L-Theanine|Theanine|Rhodiola|Boron|Copper|'
        r'Coenzyme Q|Ubiquinol|PQQ|SAMe|GABA|5-HTP|Inositol|NAC|Taurine|'
        r'Folic Acid|Folate|Choline|Iodine|Chromium|Manganese|Molybdenum|Vanadium)\b',
        title, re.I
    )
    if not nutrient_words:
        a2 = max(0, a2 - 3)
        note += " | 영양소명 없음"
    scores["A2"] = (a2, note)

    return scores


def score_B(html: str) -> dict:
    scores = {}

    # B1. og:description
    og = re.search(r'og:description.*?content="([^"]+)"', html, re.I | re.DOTALL)
    meta = re.search(r'<meta name="description" content="([^"]+)"', html, re.I)
    desc_val = og.group(1) if og else (meta.group(1) if meta else "")

    if not desc_val:
        b1, note = 0, "og:description 없음"
    elif any(t in desc_val.lower() for t in [
        "the research on zinc", "the research on ", "template", "placeholder", "write one",
        "and complete", "or complete", "studies show", "according to research",
        "what the research says", "science behind",
    ]):
        b1, note = 0, f"오염됨: {desc_val[:50]}"
    elif re.search(r'[가-힣]', desc_val):                          # 한국어 혼입
        b1, note = 0, f"한국어 혼입: {desc_val[:50]}"
    elif len(desc_val) < 80:
        b1, note = 5, f"너무 짧음 ({len(desc_val)}자)"
    elif len(desc_val) > 160:
        b1, note = 7, f"너무 김 ({len(desc_val)}자)"
    else:
        b1, note = 10, f"{len(desc_val)}자 OK"
    if not og and meta:
        b1 = min(b1, 6)
        note += " | og: 태그 없음(meta만)"
    scores["B1"] = (b1, note)

    # B2. alt 태그 — 존재 여부 + 내용 품질
    imgs = re.findall(r'<img[^>]+>', html, re.I)
    if not imgs:
        b2, note = 0, "이미지 없음"
    else:
        missing_alt = sum(1 for img in imgs if 'alt=""' in img or 'alt= ' in img or 'alt' not in img)
        short_alt   = sum(1 for img in imgs
                          if re.search(r'alt="([^"]{1,10})"', img) and 'alt=""' not in img)
        # 오염 alt 패턴: "And Complete", slug(소문자+하이픈), 템플릿 냄새
        bad_content = []
        for img in imgs:
            alt_m = re.search(r'alt="([^"]+)"', img, re.I)
            if not alt_m:
                continue
            alt = alt_m.group(1)
            if re.search(r'\bAnd Complete\b|\bor Complete\b', alt, re.I):
                bad_content.append(f"'And Complete' 잔재: {alt[:40]}")
            elif re.search(r'^\s+', alt):  # 공백으로 시작 → slug 자동생성
                bad_content.append(f"slug 패턴(공백시작): {alt[:40]}")
            elif re.search(r'#\s*\w+\s+type:', alt, re.I):     # "# nmn type: ..."
                bad_content.append(f"topic 헤더 노출: {alt[:40]}")

        if missing_alt > 0:
            b2, note = max(0, 10 - missing_alt * 3), f"{missing_alt}개 alt 없음"
        elif bad_content:
            b2, note = 3, f"alt 오염 {len(bad_content)}개: {bad_content[0]}"
        elif short_alt > 0:
            b2, note = 7, f"{short_alt}개 alt 짧음"
        else:
            b2, note = 10, f"{len(imgs)}개 alt 모두 OK"
    scores["B2"] = (b2, note)

    return scores


def score_C(html: str, title: str) -> dict:
    scores = {}
    text = re.sub(r'<[^>]+>', ' ', html)
    words = text.split()
    word_count = len(words)

    # C1. Hook (hr 사이 이탤릭)
    hook = re.search(r'<hr[^>]*>.*?<em>(.*?)</em>.*?<hr', html, re.DOTALL | re.I)
    if hook and len(hook.group(1)) > 80:
        scores["C1"] = (10, f"{len(hook.group(1))}자 hook OK")
    elif hook:
        scores["C1"] = (6, f"hook 짧음 ({len(hook.group(1))}자)")
    else:
        scores["C1"] = (0, "hook 없음")

    # C2. 섹션 제목 (H2)
    h2s = re.findall(r'<h2[^>]*>([^<]+)</h2>', html, re.I)
    if len(h2s) >= 4:
        bad_h2 = [h for h in h2s if any(w in h for w in ["Section", "Heading", "H2", "제목"])]
        if bad_h2:
            scores["C2"] = (3, f"H2 오염: {bad_h2[0][:30]}")
        else:
            scores["C2"] = (10, f"H2 {len(h2s)}개 OK")
    elif len(h2s) > 0:
        scores["C2"] = (5, f"H2 {len(h2s)}개 (권장 4+)")
    else:
        scores["C2"] = (0, "H2 없음")

    # C3. 본문 길이
    if word_count >= 1500:
        scores["C3"] = (10, f"{word_count}단어")
    elif word_count >= 1000:
        scores["C3"] = (7, f"{word_count}단어 (권장 1500+)")
    elif word_count >= 600:
        scores["C3"] = (4, f"{word_count}단어 짧음")
    else:
        scores["C3"] = (0, f"{word_count}단어 미달")

    # C4. AI 패턴 제거
    found_patterns = [p for p in AI_PATTERNS if p.lower() in text.lower()]
    if len(found_patterns) == 0:
        scores["C4"] = (10, "AI 패턴 없음")
    elif len(found_patterns) <= 2:
        scores["C4"] = (7, f"AI패턴 {len(found_patterns)}개: {found_patterns[:2]}")
    else:
        scores["C4"] = (max(0, 10 - len(found_patterns) * 2), f"AI패턴 {len(found_patterns)}개")

    # C5. 사람 블로그 느낌 (1인칭, 개인경험)
    first_person = len(re.findall(r"\bI\b|\bI've\b|\bI'm\b|\bmy\b|\bme\b", text, re.I))
    personal_phrases = len(re.findall(r"honestly|actually|personally|noticed|felt|thought|tried", text, re.I))
    if first_person >= 20 and personal_phrases >= 5:
        scores["C5"] = (10, f"1인칭 {first_person}회, 개인경험 {personal_phrases}회")
    elif first_person >= 10:
        scores["C5"] = (7, f"1인칭 {first_person}회")
    else:
        scores["C5"] = (4, f"1인칭 {first_person}회 (부족)")

    # C6. 의학 용어 밀도
    jargon_found = [j for j in MEDICAL_JARGON if j.lower() in text.lower()]
    if len(jargon_found) == 0:
        scores["C6"] = (10, "전문용어 적정")
    elif len(jargon_found) <= 2:
        scores["C6"] = (7, f"전문용어 {len(jargon_found)}개")
    else:
        scores["C6"] = (0, f"과도한 전문용어: {jargon_found[:3]}")

    return scores


def score_D(html: str) -> dict:
    scores = {}

    # D1. PMID 유효성
    pmid_links = re.findall(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', html, re.I)
    pmid_text = re.findall(r'PMID[:\s]+(\d+)', html, re.I)
    all_pmids = [int(p) for p in pmid_links + pmid_text if p.isdigit()]

    if not all_pmids:
        scores["D1"] = (0, "PMID/연구링크 없음")
    else:
        fake = [p for p in all_pmids if p > 50000000]  # 2025년 기준 PubMed 최대 ~42M
        if fake:
            scores["D1"] = (0, f"가상 PMID: {fake[:2]}")
        elif len(all_pmids) >= 3:
            scores["D1"] = (10, f"PMID {len(all_pmids)}개")
        else:
            scores["D1"] = (7, f"PMID {len(all_pmids)}개 (권장 3+)")

    # D2. 내부 링크
    internal = re.findall(r'href="https://www\.nutristacklab\.com/[^"#]+"', html, re.I)
    if len(internal) >= 2:
        scores["D2"] = (10, f"내부링크 {len(internal)}개")
    elif len(internal) == 1:
        scores["D2"] = (6, "내부링크 1개 (권장 2+)")
    else:
        scores["D2"] = (3, "내부링크 없음")

    # D3. 필수 요소 체크
    checks = {
        "hook": bool(re.search(r'<hr[^>]*>.*?<em>', html, re.DOTALL | re.I)),
        "h2": bool(re.search(r'<h2', html, re.I)),
        "img": bool(re.search(r'<img', html, re.I)),
        "disclosure": bool(re.search(r'disclosure|affiliate', html, re.I)),
        "takeaways": bool(re.search(
            r'takeaway|key.take|what i.d tell|my verdict|what i learned|key lesson'
            r'|what surprised|biggest takeaway|honest summary|would i take',
            html, re.I)),
    }
    missing = [k for k, v in checks.items() if not v]
    # 깨진 텍스트 체크
    broken = [p for p in BROKEN_TEXT_PATTERNS if re.search(p, html, re.I)]
    if broken:
        missing.append(f"broken:{broken[0][:20]}")

    if not missing:
        scores["D3"] = (10, "필수요소 모두 OK")
    elif len(missing) == 1:
        scores["D3"] = (6, f"누락: {missing}")
    else:
        scores["D3"] = (max(0, 10 - len(missing) * 3), f"누락: {missing}")

    # D4. HTML 구조 + 반복 버그 체크
    has_doctype_wrap = html.strip().startswith("<!DOCTYPE")   # 포스트에 DOCTYPE 통째로 저장된 버그
    has_style        = "<style>" in html
    has_schema       = "application/ld+json" in html
    has_double_enc   = bool(re.search(r'&amp;#\d+;', html))  # &amp;#8594; 이중인코딩
    has_toc_literal  = bool(re.search(r'content:\s*["\']?&#8594;', html))  # TOC CSS → 리터럴
    has_arrow_literal= bool(re.search(r'&#8594;', html))      # → 엔티티 잔존

    issues_d4 = []
    d4 = 10
    if has_doctype_wrap:
        d4 = 0; issues_d4.append("DOCTYPE 전체문서 저장 버그")
    if has_double_enc:
        d4 = min(d4, 2); issues_d4.append("&amp;# 이중인코딩")
    if has_toc_literal or has_arrow_literal:
        d4 = min(d4, 3); issues_d4.append("&#8594; 엔티티 잔존 (→ 로 교체 필요)")
    if not has_style:
        d4 = min(d4, 6); issues_d4.append("CSS 없음")
    if not has_schema:
        d4 = min(d4, 7); issues_d4.append("Schema.org 없음")

    scores["D4"] = (d4, ", ".join(issues_d4) if issues_d4 else "구조 OK")

    return scores


def score_E(html: str, title: str) -> dict:
    scores = {}
    text = re.sub(r'<[^>]+>', ' ', html)

    # E1. YMYL 안전성
    unsafe = re.findall(r'\bcure\b|\btreat\b|\bdiagnose\b|\bprescription\b|\bguaranteed\b|\bclinically proven\b', text, re.I)
    medical_claims = re.findall(r'will (cure|treat|prevent|eliminate|reverse)', text, re.I)
    all_unsafe = unsafe + medical_claims
    if not all_unsafe:
        scores["E1"] = (10, "YMYL 안전")
    elif len(all_unsafe) <= 2:
        scores["E1"] = (6, f"주의 문구 {len(all_unsafe)}개: {all_unsafe[:2]}")
    else:
        scores["E1"] = (0, f"위험 문구 {len(all_unsafe)}개")

    # E2. 콘텐츠 독창성
    generic = ["studies show", "research suggests", "experts recommend", "according to research"]
    generic_count = sum(text.lower().count(g) for g in generic)
    personal = len(re.findall(r"I (tried|tested|noticed|found|started|stopped|felt|thought)", text, re.I))
    if personal >= 5 and generic_count <= 3:
        scores["E2"] = (10, f"개인경험 {personal}회 OK")
    elif personal >= 3:
        scores["E2"] = (7, f"개인경험 {personal}회")
    else:
        scores["E2"] = (4, f"개인경험 부족 ({personal}회)")

    # E3. 브랜드 일관성
    has_brand = "NutriStack" in html or "nutristacklab" in html.lower()
    has_nordic = "Nordic" in html
    has_disclosure = bool(re.search(r'disclosure|affiliate', html, re.I))
    brand_score = sum([has_brand, has_nordic, has_disclosure])
    notes = []
    if not has_brand: notes.append("NutriStack 언급 없음")
    if not has_disclosure: notes.append("disclosure 없음")
    scores["E3"] = (brand_score * 3 + 1, ", ".join(notes) if notes else "브랜드 OK")

    return scores


_BLANK_NUTRIENT_TITLES = re.compile(
    r'^\s*(supplement|supplements|nutrient|nutrients)\b.*benefits',
    re.I
)

def score_F(html: str, title: str) -> dict:
    scores = {}
    text = re.sub(r'<[^>]+>', ' ', html)

    # F1. 영양소명 정확성
    # [v7.2] 플레이스홀더 제목 즉시 0점 — "Supplement Benefits, Dosage..." 류
    if _BLANK_NUTRIENT_TITLES.match(title):
        scores["F1"] = (0, f"제목이 플레이스홀더 — 실제 영양소명 없음: '{title[:60]}'")
    else:
        # 숫자 식별자(D3, K2, B12, MK-7 등)가 본문에 존재하는지 검사
        raw_idents  = re.findall(r'\b([A-Z]{1,3}\d+(?:-\d+)?)\b', title)
        identifiers = list(dict.fromkeys(i for i in raw_idents if len(i) >= 2))
        if not identifiers:
            scores["F1"] = (10, "숫자 식별자 없음 (검사 불필요)")
        else:
            missing = [i for i in identifiers
                       if not re.search(r'\b' + re.escape(i) + r'\b', text, re.I)]
            if not missing:
                scores["F1"] = (10, f"영양소명 정확 ({', '.join(identifiers)})")
            else:
                scores["F1"] = (0, f"본문 누락: {', '.join(missing)} — 제목엔 있으나 본문에 없음")

    # F2. 이미지 유효성/관련성 — hero 이미지 src 유효 + alt에 토픽 키워드 포함 여부
    # display:none / 1px 트래킹 픽셀 제외하고 첫 번째 실제 이미지 찾기
    hero_img = None
    for _m in re.finditer(r'<img[^>]+>', html, re.I):
        _tag = _m.group(0)
        if "display:none" in _tag or "width:1px" in _tag or "height:1px" in _tag:
            continue
        hero_img = _m
        break
    if not hero_img:
        scores["F2"] = (0, "이미지 없음")
    else:
        img_tag = hero_img.group(0)
        src_m   = re.search(r'src="([^"]*)"', img_tag, re.I)
        alt_m   = re.search(r'alt="([^"]*)"', img_tag, re.I)
        src     = src_m.group(1) if src_m else ""
        alt     = alt_m.group(1) if alt_m else ""

        if not src or src.startswith("data:"):
            scores["F2"] = (3, f"src 없음/base64 placeholder — 실제 이미지 URL 필요")
        else:
            # alt에 제목 핵심 키워드 포함 여부 확인
            stop = {"the","a","an","and","or","of","for","in","my","i","complete","guide","how"}
            kws  = [w.lower() for w in re.findall(r'\b[A-Za-z]{3,}\b', title)
                    if w.lower() not in stop]
            alt_lower = alt.lower()
            matched_kws = [k for k in kws if k in alt_lower]
            if matched_kws:
                scores["F2"] = (10, f"이미지 OK, alt 관련성 확인 ({', '.join(matched_kws[:3])})")
            elif alt:
                scores["F2"] = (7, f"이미지 URL OK, alt 토픽 키워드 없음: '{alt[:40]}'")
            else:
                scores["F2"] = (3, f"이미지 URL OK, alt 없음")

    return scores


# ── 즉시 REJECTED 체크
def check_instant_reject(all_scores: dict, html: str) -> list:
    rejects = []
    if all_scores.get("A1", (10,))[0] < 5:
        rejects.append(f"A1 < 5 — 제목 오염 ({all_scores['A1'][1]})")
    if all_scores.get("B1", (10,))[0] == 0:
        rejects.append(f"B1 = 0 — og:description 없음/오염")
    if all_scores.get("C3", (10,))[0] == 0:
        rejects.append(f"C3 = 0 — 1000단어 미만 ({all_scores['C3'][1]})")
    if all_scores.get("C4", (10,))[0] < 5:
        rejects.append(f"C4 < 5 — AI 패턴 과다")
    if all_scores.get("D1", (10,))[0] == 0:
        rejects.append(f"D1 = 0 — PMID/연구링크 없음")
    if all_scores.get("D3", (10,))[0] < 5:
        missing = all_scores["D3"][1]
        rejects.append(f"D3 < 5 — 필수요소 누락 ({missing})")
    broken = [p for p in BROKEN_TEXT_PATTERNS if re.search(p, html, re.I)]
    if broken:
        rejects.append(f"깨진텍스트: {broken[0]}")
    if all_scores.get("F1", (10,))[0] == 0:
        rejects.append(f"F1 = 0 — 영양소명 누락 ({all_scores['F1'][1]})")
    if all_scores.get("F2", (10,))[0] == 0:
        rejects.append(f"F2 = 0 — 이미지 없음")
    # v7.8 (v7.9 수정): 효과 과잉 — 긍정 문맥에서만 카운트
    # "no X", "didn't notice X", "I just X" 등 부정/무관 문맥 제외
    _benefit_kws = ["joint", "blood pressure", "skin", "digestion", "teeth", "sleep", "mood",
                    "vision", "hair", "nails", "memory", "libido", "testosterone"]
    def _is_positive_claim(kw, text):
        hits = re.findall(rf'.{{0,40}}\b{kw}\b.{{0,40}}', text, re.I)
        for h in hits:
            # 부정 문맥 제외 — wasn't/isn't/aren't 포함
            if re.search(
                r"\bno\b|\bnot\b|\bdidn't\b|\bdoesn't\b|\bnever\b"
                r"|\bI just\b|\bI only\b|\bwasn't\b|\bisn't\b|\baren't\b"
                r"|\bwouldn't\b|\bcouldn't\b|\bshouldn't\b"
                r"|\bslight\b|\bsubtle\b|\bnot sure\b|\bunsure\b"
                r"|\bdropping\b|\bdeficien\b|\blead to\b|\bissue\b"
                r"|\brestless\b|\banxious\b|\bworse\b|\bproblem\b|\blow\b",
                h, re.I
            ):
                continue
            return True
        return False
    _benefit_count = sum(1 for kw in _benefit_kws if _is_positive_claim(kw, html))
    if _benefit_count >= 5:
        rejects.append(f"효과 과잉 — {_benefit_count}가지 긍정 효과 나열 (최대 4가지)")
    # v7.8 (v7.9 수정): "I'd" 리스트 과잉 — <li>I'd 형태만 카운트 (과거습관 I'd been 제외)
    _id_list = len(re.findall(r"<li>[^<]*I[''']d\s+(?!been\b|had\b|already\b)", html, re.I))
    if _id_list >= 8:
        rejects.append(f"I'd 리스트 과잉 — {_id_list}개 (최대 7개)")
    # v7.9: fat 단독 과잉 — 지용성 비타민 글에서 fat-soluble 제외 15회+ 경고
    _fat_standalone = len(re.findall(r'\bfat\b', html, re.I)) - len(re.findall(r'fat.soluble', html, re.I))
    if _fat_standalone >= 15:
        rejects.append(f"fat 단독 과잉 — {_fat_standalone}회 (fat-soluble 제외, 최대 8회)")
    return rejects


# ── 리포트 생성
def make_report(post: dict) -> str:
    title = post.get("title", "")
    html  = post.get("content", "")
    url   = post.get("url", "")
    pub   = post.get("published", "")
    status = post.get("status", "LIVE")

    a = score_A(title, html)
    b = score_B(html)
    c = score_C(html, title)
    d = score_D(html)
    e = score_E(html, title)
    f = score_F(html, title)

    all_scores = {**a, **b, **c, **d, **e, **f}

    a_avg = sum(v[0] for v in a.values()) / len(a)
    b_avg = sum(v[0] for v in b.values()) / len(b)
    c_avg = sum(v[0] for v in c.values()) / len(c)
    d_avg = sum(v[0] for v in d.values()) / len(d)
    e_avg = sum(v[0] for v in e.values()) / len(e)
    f_avg = sum(v[0] for v in f.values()) / len(f)
    total = (a_avg + b_avg + c_avg + d_avg + e_avg + f_avg) / 6

    if total >= 9.0:   grade, verdict = "S", "APPROVED"
    elif total >= 8.0: grade, verdict = "A", "APPROVED"
    elif total >= 7.0: grade, verdict = "B", "조건부 승인"
    elif total >= 6.0: grade, verdict = "C", "REJECTED"
    else:              grade, verdict = "F", "즉시 REJECTED"

    rejects = check_instant_reject(all_scores, html)
    if rejects:
        verdict = "즉시 REJECTED"
        grade   = "F"

    lines = []
    lines.append("=" * 60)
    lines.append(f"NutriStack Lab 포스트 품질 검사")
    lines.append("=" * 60)
    lines.append(f"제목  : {title}")
    lines.append(f"URL   : {url}")
    lines.append(f"상태  : {status}  |  발행: {pub[:16]}")
    lines.append("")
    lines.append("[A] 제목 품질")
    for k, (s, n) in a.items():
        lines.append(f"  {k}: {s:2d}/10  {n}")
    lines.append(f"  평균: {a_avg:.1f}/10")
    lines.append("")
    lines.append("[B] 메타 데이터")
    for k, (s, n) in b.items():
        lines.append(f"  {k}: {s:2d}/10  {n}")
    lines.append(f"  평균: {b_avg:.1f}/10")
    lines.append("")
    lines.append("[C] 콘텐츠 품질")
    for k, (s, n) in c.items():
        lines.append(f"  {k}: {s:2d}/10  {n}")
    lines.append(f"  평균: {c_avg:.1f}/10")
    lines.append("")
    lines.append("[D] 기술적 완성도")
    for k, (s, n) in d.items():
        lines.append(f"  {k}: {s:2d}/10  {n}")
    lines.append(f"  평균: {d_avg:.1f}/10")
    lines.append("")
    lines.append("[E] 애드센스 가능성")
    for k, (s, n) in e.items():
        lines.append(f"  {k}: {s:2d}/10  {n}")
    lines.append(f"  평균: {e_avg:.1f}/10")
    lines.append("")
    lines.append("[F] 정확성")
    for k, (s, n) in f.items():
        lines.append(f"  {k}: {s:2d}/10  {n}")
    lines.append(f"  평균: {f_avg:.1f}/10")
    lines.append("")
    lines.append("-" * 60)
    lines.append(f"A:{a_avg:.1f}  B:{b_avg:.1f}  C:{c_avg:.1f}  D:{d_avg:.1f}  E:{e_avg:.1f}  F:{f_avg:.1f}")
    lines.append(f"종합: {total:.1f}/10  등급: {grade}  판정: {verdict}")
    lines.append("-" * 60)

    if rejects:
        lines.append("")
        lines.append("⚡ 즉시 REJECTED 사유:")
        for r in rejects:
            lines.append(f"  - {r}")

    problems = [(k, s, n) for k, (s, n) in all_scores.items() if s < 9]
    problems.sort(key=lambda x: x[1])
    if problems:
        lines.append("")
        lines.append("주요 문제 (7점 미만):")
        for k, s, n in problems[:5]:
            lines.append(f"  [{k}] {s}/10 — {n}")

    lines.append("=" * 60)
    return "\n".join(lines), all_scores


# ── 에이전트별 실패 라우팅 ────────────────────────────────────────────
def route_failures_to_agents(all_scores: dict, title: str, post_id: str) -> list:
    """
    7점 미만 항목을 담당 에이전트 lessons에 기록.
    같은 실수 HERMES_THRESHOLD회 이상 반복 시 hermes_queue.json에 추가.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    escalations = []

    # lessons 파일 로드
    lessons = {}
    if LESSONS_FILE_PATH.exists():
        try:
            lessons = json.loads(LESSONS_FILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    for cat, (score, note) in all_scores.items():
        if score >= 9:
            continue  # 9점 이상 통과

        agent_key = AGENT_ROUTING.get(cat, "03_Writer_Gardener")
        label     = CATEGORY_LABELS.get(cat, cat)
        lesson_text = f"[품질검사-{cat}] {label} {score}/10 — {note} | 포스트: {title[:40]}"

        agent_lessons = lessons.setdefault(agent_key, [])

        # 동일 카테고리 기존 항목 찾기 (count 누적)
        existing = next((e for e in agent_lessons
                         if e.get("cat") == cat and e.get("topic", "") == title[:40]), None)
        if existing:
            existing["count"]   = existing.get("count", 1) + 1
            existing["date"]    = today
            existing["score"]   = score
            existing["note"]    = note
            count = existing["count"]
        else:
            entry = {
                "date":       today,
                "cat":        cat,
                "topic":      title[:40],
                "lesson":     lesson_text,
                "score":      score,
                "note":       note,
                "count":      1,
                "first_seen": today,
            }
            agent_lessons.append(entry)
            count = 1

        # Hermes 에스컬레이션 체크
        if count >= HERMES_THRESHOLD:
            escalations.append({
                "cat":       cat,
                "agent":     agent_key,
                "label":     label,
                "score":     score,
                "note":      note,
                "count":     count,
                "title":     title[:60],
                "post_id":   post_id,
                "queued_at": today,
            })

    LESSONS_FILE_PATH.write_text(
        json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if escalations:
        _push_hermes_queue(escalations)

    return escalations


def _queue_lock_path():
    return HERMES_QUEUE_PATH.with_suffix(".lock")

def _acquire_queue_lock(timeout=10) -> bool:
    lock = _queue_lock_path()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False

def _release_queue_lock():
    try:
        _queue_lock_path().unlink(missing_ok=True)
    except Exception:
        pass

def _push_hermes_queue(items: list):
    """반복 실수를 hermes_queue.json에 추가 (Hermes 에스컬레이션)."""
    if not _acquire_queue_lock():
        print("  [Hermes 큐] lock 획득 실패 — 건너뜀")
        return
    try:
        queue = []
        if HERMES_QUEUE_PATH.exists():
            try:
                queue = json.loads(HERMES_QUEUE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        TERMINAL = {"exhausted", "done"}
        for item in items:
            existing = next((q for q in queue
                             if q.get("cat") == item["cat"] and q.get("post_id") == item.get("post_id")), None)
            if existing:
                if existing.get("status") in TERMINAL:
                    print(f"  [Hermes 큐] {item['cat']} 이미 {existing['status']} — 재큐 스킵")
                    continue
                existing.update({k: v for k, v in item.items() if k != "retry_count"})
                existing["status"] = "pending"
            else:
                item["status"] = "pending"
                item.setdefault("retry_count", 0)
                queue.append(item)

        tmp = HERMES_QUEUE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, HERMES_QUEUE_PATH)
    finally:
        _release_queue_lock()
    print(f"\n[Hermes 에스컬레이션] {len(items)}개 항목 큐에 추가 → {HERMES_QUEUE_PATH.name}")
    for it in items:
        print(f"  [{it['cat']}] {it['label']} {it['score']}/10 ({it['count']}회 반복) — {it['note']}")


def run(args):
    svc = get_service()

    if args.post_id:
        posts = get_posts(svc, post_id=args.post_id)
    elif args.scheduled:
        posts = get_posts(svc, scheduled_only=True, max_results=10)
    elif args.all:
        posts = get_posts(svc, max_results=10)
    else:
        # 기본: 오늘 발행/예약분
        posts = get_posts(svc, scheduled_only=False, max_results=20)
        today = datetime.now().strftime("%Y-%m-%d")
        posts = [p for p in posts if today in p.get("published", "")]
        if not posts:
            posts = get_posts(svc, max_results=5)

    if not posts:
        print("검사할 포스트 없음")
        return

    results = []
    for post in posts:
        report, all_scores = make_report(post)
        print(report)

        # 담당 에이전트에 실패 항목 라우팅 (7점 미만 항목만)
        post_id = post.get("id", "")
        title   = post.get("title", "")
        escalations = route_failures_to_agents(all_scores, title, post_id)

        # 에이전트별 라우팅 요약 출력
        routed = {}
        for cat, (score, note) in all_scores.items():
            if score < 9:
                ag = AGENT_ROUTING.get(cat, "unknown")
                routed.setdefault(ag, []).append(f"{cat}({score}/10)")
        if routed:
            print("\n[에이전트 라우팅]")
            for ag, cats in sorted(routed.items()):
                print(f"  {ag}: {', '.join(cats)}")
        print()
        results.append(report)

    # 로그 저장
    log_path = BASE_DIR / "20_Meta" / f"quality_check_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    log_path.write_text("\n\n".join(results), encoding="utf-8")
    print(f"리포트 저장: {log_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NutriStack 포스트 품질 검사")
    parser.add_argument("--post-id", help="특정 포스트 ID")
    parser.add_argument("--scheduled", action="store_true", help="예약 포스트만")
    parser.add_argument("--all", action="store_true", help="최근 10개 전체")
    args = parser.parse_args()
    run(args)
