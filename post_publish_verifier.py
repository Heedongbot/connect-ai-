"""
post_publish_verifier.py — 발행 직후 Critic A 최종 검증 + 수술적 수정

오케스트레이터에서 발행 완료 직후 호출:
    from post_publish_verifier import verify_and_patch
    result = verify_and_patch(
        svc, BLOG_ID, post_id, title, html, meta_desc, ask_ai, META_DIR
    )

동작:
  1. 발행된 HTML에 rule-based 품질 채점 수행
  2. 7점 미만 항목만 수술적 자동 수정 (리라이트 없음)
  3. 자동수정 불가 항목 → agent_lessons.json + hermes_queue.json 기록
  4. 결과 dict 반환 (로깅/Telegram 알림용)
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

# ── post_quality_check.py에서 채점 함수 import
try:
    from post_quality_check import (
        score_A, score_B, score_C, score_D, score_E, score_F,
        check_instant_reject, AGENT_ROUTING, CATEGORY_LABELS,
    )
    _QC_AVAILABLE = True
except ImportError:
    _QC_AVAILABLE = False

log = logging.getLogger("PostPublishVerifier")

# 즉시 자동 수정 가능 카테고리
_AUTO_FIX = {"B2", "C1", "D2", "D3", "E1"}
# 알림만 (자동수정 불가 — 내용 재작성 필요)
# B1: Blogger가 <meta> 태그를 post content에서 제거하므로 HTML 패치 불가 → 레슨만
_NOTIFY_ONLY = {"B1", "C3", "D1", "C4", "C2", "C5"}
# Hermes 큐에 즉시 등록 (발행 후 1회라도)
_HERMES_IMMEDIATE = {"A1", "A2", "F1", "F2"}


# ── 수술적 수정 함수들 ────────────────────────────────────────────────────────

# Related Posts 링크 텍스트 인간화 맵
# 새 포스팅 제목이 바뀔 때마다 여기에 추가
_RELATED_TITLE_MAP: dict[str, str] = {
    # Berberine
    "Berberine Complete: Is Berberine Worth Taking? What the Research Says":
        "Berberine Dosage: The Mistake That Delayed My Results",
    "Berberine Complete":
        "Berberine Dosage: The Mistake That Delayed My Results",
    "Is Berberine Worth Taking What the Research Says":
        "Berberine Dosage: The Mistake That Delayed My Results",
    "The Berberine Mistake That Made Me Want to Quit":
        "Berberine Dosage: The Mistake That Delayed My Results",
    # Magnesium
    "Magnesium Complete Guide: Benefits, Types, and Best Dosage":
        "Magnesium Types and Dosage: The Form That Finally Worked for Me",
    "Magnesium Benefits Types and Best Dosage":
        "Magnesium Types and Dosage: The Form That Finally Worked for Me",
    "Magnesium Benefits, Types, and Best Dosage":
        "Magnesium Types and Dosage: The Form That Finally Worked for Me",
    "Magnesium: Benefits, Types, and Best Dosage":
        "Magnesium Types and Dosage: The Form That Finally Worked for Me",
    # Vitamin C
    "Vitamin C: What I Found After Months of Testing (Complete Guide)":
        "Vitamin C Dosage: What Six Months of Testing Actually Taught Me",
    "Vitamin C: What I Found After Months of Testing ()":
        "Vitamin C Dosage: What Six Months of Testing Actually Taught Me",
    "Vitamin C: What I Found After Months of Testing":
        "Vitamin C Dosage: What Six Months of Testing Actually Taught Me",
    "Vitamin C: What Months of Testing Actually Taught Me":
        "Vitamin C Dosage: What Six Months of Testing Actually Taught Me",
    # Vitamin K2
    "The Complete Vitamin K2 (MK7) Guide: Science, Pairing, and Routine":
        "Vitamin K2 (MK7) Dosage: What I Learned About Timing and Stacking",
    # Ashwagandha
    "How to Use Ashwagandha effectively: A Simple Guide":
        "Ashwagandha Dosage: What It Actually Did for My Sleep and Stress",
    # Citrulline — 구 제목 전부 최신 제목으로
    "Why Citrulline Malate Changed My Routine Completely":
        "Why Citrulline Malate Felt Useless Until Week Four",
    "Citrulline Malate Dosage Guide: How Much Do You Need?":
        "Why Citrulline Malate Felt Useless Until Week Four",
    "Citrulline Malate Dosage: Why I Added It (And What Happened)":
        "Why Citrulline Malate Felt Useless Until Week Four",
    # Vitamin D3
    "Vitamin D3: Guide to Dosage and Benefits":
        "The Vitamin D Mistake That Kept Me Tired",
    "Vitamin D3: Guide to dosage and benefits":
        "The Vitamin D Mistake That Kept Me Tired",
    # Probiotics
    "Probiotics Complete: Probiotics : Guide to Dosage and Benefits":
        "Probiotics Dosage: How Much You Actually Need (And When)",
    "Probiotics Complete: Probiotics Dosage Guide: How Much Do You Need?":
        "Probiotics Dosage: How Much You Actually Need (And When)",
    "Probiotics Dosage Guide":
        "Probiotics Dosage: How Much You Actually Need (And When)",
    "Probiotics Benefits: Boost Immune System & Improve Digestion":
        "Probiotics Dosage: How Much You Actually Need (And When)",
    "Probiotics: Probiotics Dosage Guide: How Much Do You Need?":
        "Probiotics Dosage: How Much You Actually Need (And When)",
    # NMN
    "NMN Complete: Is NMN Worth Taking? What the Research Says":
        "NMN Supplement: The Timing Mistake That Delayed My Results",
    "NMN: Is NMN Worth Taking? What the Research Says":
        "NMN Supplement: The Timing Mistake That Delayed My Results",
    "The NMN Mistake That Delayed My Results":
        "NMN Supplement: The Timing Mistake That Delayed My Results",
    # Iron
    "Iron: How I Actually Fixed My Energy (After Months of Failing)":
        "Iron Deficiency: How I Finally Fixed My Energy Levels",
    # B12
    "Is Vitamin B12 Worth Taking? What the Research Says":
        "Vitamin B12 Absorption: Why I Got It Wrong for Months",
    "The B12 Mistake That Kept Me Tired":
        "Vitamin B12 Absorption: Why I Got It Wrong for Months",
}


# ============================================================
# EDITOR RULES v1.0 — 7개 후처리 검수 룰
# Writer 품질 교육 → 자동 수정 후 글 파손 방지로 Teacher 역할 전환
# ============================================================

def _editor_rule1_substitution_duplicates(html: str) -> list[str]:
    """Rule 1: 치환 후 중복 구문 탐지.
    예: 'That Finally Made a Difference That Finally Made a Difference'
    """
    issues = []
    plain = re.sub(r'<[^>]+>', ' ', html)
    plain = re.sub(r'\s+', ' ', plain)
    # 4단어 이상 반복 구문
    words = plain.split()
    for length in (5, 6, 7, 8):
        for i in range(len(words) - length * 2 + 1):
            phrase = ' '.join(words[i:i+length])
            following = ' '.join(words[i+length:i+length*2])
            if phrase.lower() == following.lower() and len(phrase) > 20:
                issues.append(f"중복 구문: '{phrase[:60]}' 연속 등장")
    return issues


def _editor_rule2_broken_sentences(html: str) -> list[str]:
    """Rule 2: 치환 사고로 인한 문장 파손 탐지.
    예: 'health.simultaneously', 'work.however', 'day.the'
    """
    issues = []
    plain = re.sub(r'<[^>]+>', ' ', html)
    # 소문자 단어.소문자 단어 (URL, 숫자 제외)
    broken = re.findall(r'\b([a-z]{3,})\.(simultaneously|however|therefore|the|this|that|when|it|i |my |he |she |they |we |you )', plain, re.I)
    for w1, w2 in broken:
        issues.append(f"문장 파손: '{w1}.{w2}' — 마침표 뒤 공백 없음")
    # 소문자로 시작하는 <p> 태그
    lc_p = re.findall(r'<p[^>]*>\s*([a-z])', html)
    if len(lc_p) > 3:
        issues.append(f"소문자 시작 <p> {len(lc_p)}개 — 치환 사고 가능성")
    return issues


def _editor_rule3_title_sync(html: str, title: str) -> list[str]:
    """Rule 3: H1 / OG Title / JSON-LD headline 100% 동일 검사."""
    issues = []
    h1_m   = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.I | re.S)
    ogt_m  = re.search(r'property=["\']og:title["\'][^>]*content="([^"]+)"', html, re.I)
    jld_m  = re.search(r'"headline"\s*:\s*"([^"]+)"', html)

    h1    = re.sub(r'<[^>]+>', '', h1_m.group(1)).strip()  if h1_m  else '(없음)'
    og_t  = ogt_m.group(1).strip()                          if ogt_m else '(없음)'
    jld_t = jld_m.group(1).strip()                          if jld_m else '(없음)'

    if not (h1 == og_t == jld_t):
        issues.append(
            f"제목 3곳 불일치:\n  H1      : {h1[:60]}\n  OG      : {og_t[:60]}\n  JSON-LD : {jld_t[:60]}"
        )
    return issues


def _editor_rule4_desc_sync(html: str) -> list[str]:
    """Rule 4: OG Description / JSON-LD description 동일 검사."""
    issues = []
    ogd_m  = re.search(r'property=["\']og:description["\'][^>]*content="([^"]+)"', html, re.I)
    jldd_m = re.search(r'"description"\s*:\s*"([^"]+)"', html)
    jsd_m  = re.search(r'var\s+desc\s*=\s*"([^"]+)"', html)

    og_d  = ogd_m.group(1).strip()  if ogd_m  else ''
    jld_d = jldd_m.group(1).strip() if jldd_m else ''
    js_d  = jsd_m.group(1).strip()  if jsd_m  else ''

    # apostrophe 정규화 후 비교
    def norm(s): return s.replace("&#39;", "'").replace("&apos;", "'").replace('’', "'")
    og_n, jld_n, js_n = norm(og_d), norm(jld_d), norm(js_d)

    if og_n and jld_n and og_n != jld_n:
        issues.append(f"Description 불일치:\n  OG     : {og_d[:80]}\n  JSON-LD: {jld_d[:80]}")
    if og_n and js_n and og_n != js_n:
        issues.append(f"Description 불일치:\n  OG : {og_d[:80]}\n  JS : {js_d[:80]}")
    return issues


def _editor_rule5_experience_ratio(html: str, topic_type: str = "") -> list[str]:
    """Rule 5: 포스트 타입별 경험담 비율 검사 (내경험 + 주변인 경험 통합).
    - comprehensive_guide          : 45~55%
    - how_i_use / personal_guide   : 60~75%
    - experiment_log               : 60~70%
    - wrong_culprit                : 65~80%
    - unexpected_tradeoff          : 65~80%
    - regret_ignoring              : 65~80%
    - 기타 experience/longtail     : 60~75%

    경험담 = 내경험(I/my/me) + 주변인경험(친구/파트너/지인/포럼 등)
    내경험 : 주변인 권장 비율 = 2 : 8
    """
    _RATIO_MAP = {
        "comprehensive_guide":  (0.45, 0.55, "Comprehensive Guide 기준 45~55%"),
        "how_i_use":            (0.60, 0.75, "How I Use 기준 60~75%"),
        "personal_guide":       (0.60, 0.75, "Personal Guide 기준 60~75%"),
        "experiment_log":       (0.60, 0.70, "Experiment Log 기준 60~70%"),
        "wrong_culprit":        (0.65, 0.80, "Wrong Culprit 기준 65~80%"),
        "unexpected_tradeoff":  (0.65, 0.80, "Unexpected Tradeoff 기준 65~80%"),
        "regret_ignoring":      (0.65, 0.80, "Regret Ignoring 기준 65~80%"),
    }
    _DEFAULT = (0.60, 0.75, "경험담 기준 60~75%")

    t = (topic_type or "").lower().strip()
    lo, hi, label = _RATIO_MAP.get(t, _DEFAULT)

    issues = []
    plain = re.sub(r'<[^>]+>', ' ', html)
    sentences = [s.strip() for s in re.split(r'[.!?]', plain) if len(s.strip()) > 20]
    if not sentences:
        return issues

    # ── 내 경험담 마커 ────────────────────────────────────────────
    personal_markers = re.compile(
        r'\b(I |I\'ve |I was |I\'m |I noticed |I tried |I found |I started |'
        r'my |me |myself |for me |felt |noticed |realized |decided )\b', re.I
    )
    # ── 주변인 경험담 마커 ────────────────────────────────────────
    social_markers = re.compile(
        r'\b(my friend|my partner|my wife|my husband|my girlfriend|my boyfriend|'
        r'my mom|my dad|my mother|my father|my sister|my brother|my colleague|'
        r'my coworker|my trainer|my coach|my doctor|my roommate|'
        r'a friend of mine|one of my friends|someone I know|a guy I know|'
        r'a woman I know|people I know|someone at the gym|a guy at the gym|'
        r'someone on reddit|a reddit thread|someone mentioned|'
        r'someone told me|people around me|others I\'ve talked to|'
        r'a few people I know)\b', re.I
    )

    # social_markers 우선 분류 (my friend > my 패턴 충돌 방지)
    personal_count = 0
    social_count   = 0
    for s in sentences:
        if social_markers.search(s):
            social_count += 1
        elif personal_markers.search(s):
            personal_count += 1
    exp_count = personal_count + social_count
    ratio = exp_count / len(sentences)

    # ① 전체 경험담 비율 체크
    if ratio < lo:
        issues.append(
            f"경험담 비율 {ratio:.0%} 미달 ({label}) — "
            f"설명 {len(sentences)-exp_count}개 vs 경험(내{personal_count}+주변{social_count})개"
        )
    elif ratio > hi:
        issues.append(
            f"경험담 비율 {ratio:.0%} 초과 ({label}) — 설명/정보 문장이 더 필요함"
        )

    # ② 내경험 : 주변인 비율 서브체크 — friend_experience 타입만 적용
    # comprehensive_guide/timing/synergy 등은 개인 경험 위주가 자연스러움
    _social_check_types = {"friend_experience", "wrong_culprit", "regret_ignoring"}
    if t in _social_check_types and exp_count >= 5 and social_count < personal_count * 0.5:
        issues.append(
            f"주변인 경험담 부족 — 내경험 {personal_count}개 vs 주변인 {social_count}개 "
            f"(권장 비율 2:8 — 친구/파트너/지인/포럼 경험 추가 필요)"
        )

    return issues


def _editor_rule6_exaggeration(html: str) -> list[str]:
    """Rule 6: 과장 표현 탐지 + 근거 문단 존재 여부 확인."""
    issues = []
    plain = re.sub(r'<[^>]+>', ' ', html).lower()

    EXAGGERATIONS = [
        'everything changed', 'life changing', 'life-changing',
        'completely transformed', 'miracle', 'miraculous',
        'incredible results', 'dramatic improvement', 'totally different person',
        'changed my life', 'never looked back',
    ]
    EVIDENCE_MARKERS = ['study', 'research', 'pmid', 'trial', 'published', 'evidence', 'data']

    found = [e for e in EXAGGERATIONS if e in plain]
    if found:
        has_evidence = any(m in plain for m in EVIDENCE_MARKERS)
        if not has_evidence:
            issues.append(
                f"과장 표현 + 근거 없음: {found[:3]} — "
                "연구/PMID 인용 없이 과장적 표현 사용"
            )
    return issues


def _editor_rule7_reader_perspective(html: str, title: str, ask_ai_fn) -> list[str]:
    """Rule 7: 발행 전 독자 시점 검사 (가장 중요).
    Claude에게 독자 입장에서 4가지 질문 답하게 함.
    답 못하면 FAIL.
    """
    issues = []
    if ask_ai_fn is None:
        return issues

    plain = re.sub(r'<[^>]+>', ' ', html)
    plain = re.sub(r'\s+', ' ', plain).strip()
    excerpt = plain[:4000]  # 앞 4000자만 사용 (비용 절감)

    prompt = f"""Read this article excerpt as a first-time visitor. Ignore HTML, JSON-LD, and SEO.

Title: {title}

Article excerpt:
{excerpt}

Answer ONLY these 4 questions in JSON:
{{
  "story": "one sentence: what happened to the author?",
  "what_changed": "one sentence: what specific change did they notice?",
  "mistake": "one sentence: what mistake did the author make?",
  "title_fulfilled": true or false
}}

If you cannot answer any question from the text, use null."""

    try:
        raw = ask_ai_fn(prompt, "You are a first-time blog reader. Be honest and brief.")
        # JSON 추출
        m = re.search(r'\{[^{}]+\}', raw, re.S)
        if not m:
            issues.append("Rule7: 독자 시점 응답 파싱 실패")
            return issues

        data = json.loads(m.group())
        nulls = [k for k, v in data.items() if v is None or v == 'null']
        if nulls:
            issues.append(
                f"Rule7 독자 시점 FAIL — 답 불가 항목: {nulls}. "
                "독자가 이야기/변화/실수/제목 이행 중 일부를 파악 못함"
            )
        if data.get('title_fulfilled') is False:
            issues.append(
                f"Rule7 제목 미이행 — 제목 '{title[:50]}' 이 본문에서 약속한 것을 이행하지 않음"
            )
    except Exception as e:
        log.warning(f"  [Rule7] 독자 시점 검사 실패 (무시): {e}")

    return issues


def _editor_rule8_image_urls(html: str) -> list[str]:
    """Rule 8: 이미지 URL 유효성 검사.
    깨진 이미지(404/timeout/error)를 감지. Imgur 링크 우선 확인.
    최대 6개 이미지, 각 5초 타임아웃.
    """
    import urllib.request
    issues = []

    # img src 추출
    img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
    # og:image도 포함
    og_imgs  = re.findall(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    all_urls = list(dict.fromkeys(img_urls + og_imgs))  # 중복 제거

    if not all_urls:
        return issues

    # Imgur 우선, 나머지는 뒤로 (최대 6개)
    imgur_urls = [u for u in all_urls if 'imgur.com' in u]
    other_urls = [u for u in all_urls if 'imgur.com' not in u]
    check_urls = (imgur_urls + other_urls)[:6]

    # CDN별 정책:
    # - Imgur: timeout/연결오류도 broken으로 처리 (자주 링크 사망)
    # - Unsplash/Google/Drive 등 대형 CDN: 확실한 404만 처리 (느린 것은 무시)
    CDN_STRICT = ('imgur.com',)                         # 엄격 체크
    CDN_LENIENT = ('unsplash.com', 'googleusercontent', # 404만 체크
                   'drive.google.com', 'blogger.com',
                   'lh3.googleusercontent', 'bp.blogspot')

    for url in check_urls:
        if not url.startswith('http'):
            continue
        is_strict  = any(d in url for d in CDN_STRICT)
        is_lenient = any(d in url for d in CDN_LENIENT)
        timeout    = 5 if is_strict else 8
        try:
            req = urllib.request.Request(url, method='HEAD',
                headers={'User-Agent': 'Mozilla/5.0 NutriStackBot'})
            resp = urllib.request.urlopen(req, timeout=timeout)
            if resp.status == 404:
                issues.append(f"이미지 404 (없음): {url[:80]}")
            elif resp.status >= 400 and is_strict:
                issues.append(f"이미지 HTTP {resp.status}: {url[:80]}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                issues.append(f"이미지 404 (없음): {url[:80]}")
            elif e.code >= 400 and is_strict:
                issues.append(f"이미지 HTTP {e.code}: {url[:80]}")
        except Exception as e:
            err = str(e)[:50]
            # Imgur만 timeout/연결오류도 broken으로 처리
            if is_strict:
                issues.append(f"이미지 접근 불가 (Imgur): {url[:80]}")
            # Unsplash/CDN timeout은 무시

    return issues


def run_editor_checks(html: str, title: str, ask_ai_fn=None, topic_type: str = "") -> list[dict]:
    """8개 Editor 룰 전체 실행. 각 이슈를 dict 리스트로 반환."""
    all_issues = []

    checks = [
        ("RULE1_DUPLICATE",   "치환 중복",       "medium", _editor_rule1_substitution_duplicates(html)),
        ("RULE2_BROKEN",      "문장 파손",       "high",   _editor_rule2_broken_sentences(html)),
        ("RULE3_TITLE_SYNC",  "제목 동기화",     "high",   _editor_rule3_title_sync(html, title)),
        ("RULE4_DESC_SYNC",   "설명 동기화",     "medium", _editor_rule4_desc_sync(html)),
        ("RULE5_EXP_RATIO",   "경험담 비율",     "medium", _editor_rule5_experience_ratio(html, topic_type)),
        ("RULE6_EXAGGERATION","과장 탐지",       "high",   _editor_rule6_exaggeration(html)),
        ("RULE8_IMAGE_URL",   "이미지 URL 깨짐", "high",   _editor_rule8_image_urls(html)),
    ]

    for code, label, severity, msgs in checks:
        for msg in msgs:
            all_issues.append({
                "category": code, "message": msg,
                "severity": severity, "label": label
            })
            log.warning(f"  [Editor-{code}] {msg[:100]}")

    # Rule 7은 AI 호출 필요 (비용 있으므로 이슈 있을 때만 실행 OR 항상)
    r7 = _editor_rule7_reader_perspective(html, title, ask_ai_fn)
    for msg in r7:
        all_issues.append({
            "category": "RULE7_READER",
            "message": msg,
            "severity": "critical",
            "label": "독자 시점 검사"
        })
        log.warning(f"  [Editor-RULE7] {msg[:100]}")

    if not all_issues:
        log.info("  [Editor] ✅ 7개 룰 전부 통과")

    return all_issues


def _fix_bad_alts(html: str) -> tuple[str, list]:
    """오염된 이미지 alt 텍스트 자동 수정.
    - 'And Complete' / 'or Complete' 잔재
    - '# nutrient type: ...' topic 헤더 노출
    - 전부 소문자+공백 slug 패턴
    """
    fixed = []

    def clean_alt(m):
        tag = m.group(0)
        alt_m = re.search(r'(alt=")([^"]+)(")', tag, re.I)
        if not alt_m:
            return tag
        alt = alt_m.group(2)
        new_alt = None

        if re.search(r'\bAnd Complete\b|\bor Complete\b', alt, re.I):
            # "Nmn and Complete supplements..." → "my NMN bottle next to breakfast"
            new_alt = re.sub(r'\s*[Aa]nd Complete\b|\s*[Oo]r Complete\b', '', alt).strip()
            if not new_alt or len(new_alt) < 8:
                new_alt = "my supplement bottle next to breakfast"
            fixed.append(f"alt 'And Complete' 제거: '{alt[:40]}'")

        elif re.search(r'guide\s+weeks?\s*\d', alt, re.I):
            # "vitamin k2 guide weeks 1–2: what i expected vs. reality"
            new_alt = "my notes from the first two weeks"
            fixed.append(f"alt guide-weeks 패턴 제거: '{alt[:40]}'")

        elif re.search(r'testing\s+\w[\w\s]{0,20}during\s+week', alt, re.I):
            # "testing K2 during week three" → AI 설명 느낌
            new_alt = "my K2 bottle after week three"
            fixed.append(f"alt testing-during-week 패턴 제거: '{alt[:40]}'")

        elif re.search(r'expected\s+vs\.?\s*reality', alt, re.I):
            # "what i expected vs. reality" 패턴
            new_alt = "the bottle I almost stopped using"
            fixed.append(f"alt expected-vs-reality 패턴 제거: '{alt[:40]}'")

        elif re.search(r'^#\s*\w+\s+type:', alt, re.I):
            # "# nmn type: comprehensive guide..." → 제거 후 기본값
            new_alt = "my supplement setup during the trial period"
            fixed.append(f"alt topic헤더 제거: '{alt[:40]}'")

        elif re.search(r'^\s+', alt):
            # 공백으로 시작하는 alt → slug 자동생성 흔적
            new_alt = alt.strip().capitalize()
            fixed.append(f"alt 공백시작 수정: '{alt[:40]}'")

        if new_alt and new_alt != alt:
            tag = tag[:alt_m.start(2)] + new_alt + tag[alt_m.end(2):]
        return tag

    new_html = re.sub(r'<img[^>]+>', clean_alt, html, flags=re.I)

    # v7.6: 이미지 캡션 AI 흔적 수정 (이미지 바로 아래 <div> 안 이탤릭 텍스트)
    _CAPTION_BADS = [
        # "Personal observations on X And Y" / "Personal observations on X"
        (r'Personal observations on [\w\s]+And[\w\s]+\.',
         'The bottle I almost stopped taking after week two.'),
        (r'Personal observations on [\w\s]+\.',
         'My setup during the trial period.'),
        # "What changed after I stopped ignoring [H2 slug]"
        (r'What changed after I stopped ignoring\s+[\w\s]+\.',
         'My workout notes from the first month.'),
        # "Adjusting my X And Complete routine for the season"
        (r'Adjusting my [\w\s]+And Complete[\w\s]+\.',
         'The bottle I almost stopped taking after week two.'),
        # "A simple setup for my morning X routine"
        (r'A simple setup for my morning [\w\s]+routine\.',
         'My morning setup during week three.'),
    ]
    for pat, repl in _CAPTION_BADS:
        new_html2, n = re.subn(pat, repl, new_html, flags=re.I)
        if n:
            fixed.append(f"캡션 AI흔적 수정: '{pat[:40]}' ({n}회)")
            new_html = new_html2

    return new_html, fixed


def _fix_related_titles(html: str) -> tuple[str, list]:
    """Related Posts 링크 텍스트를 인간화 맵으로 일괄 치환."""
    fixed = []
    # 긴 문자열 우선 매칭 (부분 일치 방지)
    for old, new in sorted(_RELATED_TITLE_MAP.items(), key=lambda x: -len(x[0])):
        if old in html:
            html = html.replace(old, new)
            fixed.append(f"Related '{old[:45]}' → '{new[:45]}'")
    return html, fixed


def _fix_e1_ymyl(html: str) -> tuple[str, list]:
    """YMYL 위험 표현 → 안전 표현 치환"""
    replacements = [
        (r'\bcure\b',                    'support'),
        (r'\btreat\b',                   'help with'),
        (r'\bdiagnose\b',                'identify'),
        (r'\bprescription\b',            'recommendation'),
        (r'\bguaranteed\b',              'may help'),
        (r'\bclinically proven\b',       'studied'),
        (r'will (cure|treat|prevent|eliminate|reverse)', 'may help with'),
    ]
    changed = []
    for pattern, repl in replacements:
        new_html, n = re.subn(pattern, repl, html, flags=re.I)
        if n:
            changed.append(f"'{pattern}' → '{repl}' ({n}회)")
            html = new_html
    return html, changed


def _fix_ai_phrases(html: str) -> tuple[str, list]:
    """AI 흔적 구문 → 자연스러운 표현으로 치환"""
    replacements = [
        # AI 패턴 구문
        (r'\bsignificant advancement\b',    'noticeable difference'),
        (r'\bsignificant advancements\b',   'noticeable differences'),
        (r'\bgame[- ]changer\b',            'useful addition'),
        (r'\bgame[- ]changing\b',           'effective'),
        (r'\bReal [Tt]alk[:\s]',            "Here's what I found: "),
        (r'\bdelve into\b',                 'look at'),
        (r'\bdelving into\b',               'looking at'),
        (r'\bit\'s worth noting\b',         'worth knowing'),
        (r'\bit is worth noting\b',         'worth knowing'),
        (r'\bit is important to note\b',    'worth knowing'),
        (r'\bit\'s important to note\b',    'worth knowing'),
        (r'\bit should be noted\b',         'worth knowing'),
        (r'\bit is worth mentioning\b',     'worth knowing'),
        (r'\bin conclusion,?\s*',           'Overall, '),
        (r'\bto summarize,?\s*',            'Overall, '),
        (r'\bin summary,?\s*',              'Overall, '),
        (r'\bnoticeable improvements in\b', 'better'),
        (r'\bprotocol\b',                   'routine'),
        (r'\bbioavailable\b',               'absorbable by the body'),
        # 학술/AI 전환어 — 개인 블로그에 부자연스러움
        (r'\bFurthermore,?\s*',             'Also, '),
        (r'\bMoreover,?\s*',                'Also, '),
        (r'\bAdditionally,?\s*',            'Also, '),
        (r'\bConsequently,?\s*',            'So '),
        (r'\bSubsequently,?\s*',            'After that, '),
        (r'\bNevertheless,?\s*',            'Still, '),
        (r'\bNonetheless,?\s*',             'Still, '),
        (r'\bHereby\b',                     ''),
        (r'\bNeedless to say,?\s*',         ''),
        (r'\bIt goes without saying\b',     'Obviously'),
        (r'\bas we can see,?\s*',           ''),
        (r'\bAs mentioned (?:above|earlier|previously),?\s*', ''),
        (r'\bIn this (?:article|post|blog post),?\s*(?:we will|I will|I\'ll|we\'ll)\s*', 'Here, '),
        (r'\bBy the end of this (?:article|post),?\s*',       'After reading this, '),
        # AI 흥미 과잉 표현
        (r'\bIt\'?s fascinating\b',         'Interesting'),
        (r'\bplays a crucial role\b',       'matters a lot'),
        (r'\bplays a vital role\b',         'matters'),
        (r'\bplays an important role\b',    'matters'),
        (r'\bcutting[- ]edge\b',            'newer'),
        (r'\bstate[- ]of[- ]the[- ]art\b',  'current'),
        (r'\bparadigm shift\b',             'shift'),
        (r'\bgroundbreaking\b',             'notable'),
        (r'\brevolutionary\b',              'different'),
        (r'\bnordic science\b',             'research'),
        # 연구 강조 AI 투
        (r'\bstudies have shown\b',         'research suggests'),
        (r'\bstudies have demonstrated\b',  'research suggests'),
        (r'\bevidence-based\b',             'research-backed'),
        (r'\bscientifically proven\b',      'studied'),
        (r'\blet\'?s (?:dive|dive deep) into\b', "here's"),
        (r'\blet\'?s explore\b',            "here's what I found about"),
        (r'\blook no further\b',            ''),
        # 과장 메타포
        (r'\bwarzone\b',                    'rough stretch'),
        (r'\bbattlefield\b',                'rough patch'),
        (r'\bhamster wheel\b',              'cycle'),
        (r'\bwhat actually worked\b',        'what ended up helping'),
        (r'\bwhat actually changed\b',       'what shifted'),
        (r'\bwhat actually happened\b',      'what I noticed'),
        (r'\bwhat actually noticed\b',       'what stood out'),
        # "Complete Guide" in body text (제목이 아닌 본문 내 잔재)
        (r'\bComplete Guide\b',              'guide'),
        # consistency 강의 투 패턴
        (r'\bconsistency is everything\b',  'the pattern I built around it mattered most'),
        (r'\bconsistency is key\b',         'not skipping more than a day or two made the difference'),
        (r'\bconsistency is what matters\b','the gaps hurt more than the missed doses'),
        (r'\bno exceptions\b',              'or close to it'),
        # fat + 흡수 조합 — B12/수용성 비타민에서 잘못된 정보
        (r'\bfat.containing meal\b',        'regular meal'),
        (r'\bmeal containing fat\b',        'proper meal'),
        (r'\bfat helps?\s+(?:with\s+)?absorption\b', 'taking it with food helps'),
        (r'\bmiracle molecule\b',           'longevity supplement'),
        (r'\bnew level of productivity\b',  'slightly more consistent output'),
        (r'\baging slower\b',               'feeling less drained over time'),
        (r'\bI was thriving\b',             'I felt more stable'),
        (r"I wasn['']t just surviving[—\-–]+I was thriving\.?",
                                            'I felt more stable.'),
        (r'\bhuman supercomputer\b',        'sharper version of myself'),
        (r'\bswallowed a (greasy )?sock\b', 'tasted off'),
        (r'\bswallowed a brick\b',          'felt heavy'),
        # v7.7: 문장 중간 대문자 오류 (LLM 생성 흔적)
        (r',\s+It wasn\'t',          ", it wasn't"),
        (r',\s+But It wasn\'t',      ', but it wasn\'t'),
        (r'\bthat Not skipping\b',   'that not skipping'),
        # v7.7: 문법 오류 자동 수정
        (r'\bwasn\'t a instant\b',          "wasn't an instant"),
        (r'\bwas a instant\b',              'was an instant'),
        (r'\bisn\'t a instant\b',           "isn't an instant"),
        (r'\bnot a instant\b',              'not an instant'),
        # v7.7: "routine D3" → "D3 routine" 어순 오류 (fat-soluble 영양소 공통)
        (r'\bthis routine (D3|Vitamin D3|vitamin d3)\b', r'this \1 routine'),
        (r'\bmy routine (D3|Vitamin D3|vitamin d3)\b',   r'my \1 routine'),
        # v7.7: fat 반복 과잉 — 설명 외 나머지 치환
        (r'\btaken with a fatty snack\b',   'taken with dinner'),
        (r'\bwith a fat source\b',          'with breakfast'),
        (r'\btiming, fat intake, and\b',    'timing and'),
        # v7.7: "may support-all" / "may support" 생성 오류
        (r'\ba may support-all\b',              'a magic fix'),
        (r'\bmay support-all\b',                'magic fix'),
        (r'\ba miracle may support\b',          'a miracle fix'),
        (r'\bthe \w+ is a instant fix\b',       r'the supplement is an instant fix'),
        # v7.7: "stable afternoon energy" footprint 패턴 — 문맥 깨짐 방지를 위해 body/sec 내에서만 치환
        (r'\bstable afternoon energy\b',        'afternoon energy improvement'),
        (r'\bimmediate stable \w[\w\s]*energy\b', 'immediate energy improvement'),
        # v7.7: "less of an afternoon slump" replace_all 후 문장 깨짐 방지
        (r'\binitial less of an afternoon slump\b', 'early afternoon slump'),
        (r'\bimmediate less of an afternoon slump\b', 'immediate energy lift'),
        # v7.6: PMID 배너 형태 제거 — 개인 경험 블로그에 부자연스러운 논문 검증 배너
        # 예: (Data published under PMID 38718794 validates the physiological response discussed here.)
        (r'\(Data published under PMID\s+\d+\s+validates[^)]+\)',  ''),
        (r'<p[^>]*><em>\(Data published under PMID[^<]+</em></p>\n?', ''),
        # v7.6: hook 내 구 제목 잔재
        (r"Here's what I learned from weeks of trial and error\.", 'Turns out I\'d been taking it wrong the whole time.'),
        # v7.6: research 강조 배너 → 개인 경험 톤으로
        (r'\bSo I did the thing I hate most[—\-–]+research\b', 'I later found an explanation that made sense'),
        (r'\bI did the thing I hate most[—\-–]+research\b',    'I later found an explanation that made sense'),
        # v7.6: consistency 단어 과잉 — 3종 직접 반복 패턴
        (r'\bThe key is consistency\.\b',   'Pre-workout timing and the dose split are what actually matter.'),
        (r'\bconsistency of the results\b', 'how steady the results have been'),
        (r'\bif you\'?re consistent with how you take it\b', 'if you actually stick with it'),
        # v7.6: take it with food 과잉 — food-first 영양제 아닌 경우
        (r'\bTake it with food[—\-–]not on an empty stomach\.\s*', ''),
        (r'\btaken properly with meals\b',  'taken on a regular schedule'),
        (r'\bpaired it with meals[—\-–][^.]+\.', 'committed to the pre-workout timing.'),
        # v7.8: K2/지용성 비타민 단위 오류 — mg → mcg
        (r'\b(\d+)\s*mg\b(?=[^<]{0,60}(?:vitamin k2|mk-7|mk7))',  r'\1 mcg'),
        # v7.8: Maybe It / but It / why It 문장 중간 대문자
        (r'\bMaybe It\b',                   'Maybe it'),
        (r"\bthat's why It\b",              "that's why it"),
        (r'\bbut It wasn\'t\b',             "but it wasn't"),
        (r'\bwhy It wasn\'t\b',             "why it wasn't"),
        # v7.9: og:description 내 "and complete" / "or complete" 흔적
        (r'\band complete experiment\b',    'and my experience'),
        (r'\bvitamin and complete\b',       'vitamin experience'),
        (r'\bor complete\b(?=[^<]{0,50}(?:experiment|guide|post))', 'experience'),
        # v7.9: Alt 텍스트 AI 설명 패턴 (testing X during week)
        (r'testing\s+\w[\w\s]{0,20}during\s+week\s*\w+',
         'my bottle after week three'),
        # v7.9 후속: 저자명 오타 — Eric → Erik
        (r'\bEric Lindström\b',             'Erik Lindström'),
        # v7.9 후속: "started this routine X" → "started taking X"
        (r'\bI started this routine\b',     'I started taking'),
        (r'\bstarted this routine\b',       'started taking'),
        # v7.9 후속: 오타 자동 수정
        (r'\bdiscoverys\b',                 'discoveries'),
        (r'\brecoverys\b',                  'recoveries'),
        (r'\bhelpd\b',                      'helped'),
        (r'\bdna\b',                        'DNA'),
        (r'\brna\b',                        'RNA'),
        # v7.9 후속: 문법 오류
        (r'\bmight not had\b',              'might not have'),
        (r'\bcould not had\b',              'could not have'),
        (r'\bwould not had\b',              'would not have'),
        # v7.9 후속: HMB 지용성/수용성 오류 (HMB는 water-soluble)
        (r'\bHMB is fat.soluble\b',         'HMB is water-soluble'),
        (r'\btake HMB with fat\b',          'take HMB before training'),
        (r'\bHMB needs fat\b',              'HMB needs consistency'),
        # v7.9 후속: FAQ 문장 dash 연결 오류 ("consistency mattered.—stick with it")
        (r'(consistency mattered[^.]*)\.[—–-]+([Ss]tick with it)',
         r'\1. \2'),
        (r'(mattered more than anything else)\.[—–-]+([Ss]tick)',
         r'\1. \2'),
        # v7.9 후속: fat 치환 사고 복구 패턴
        (r'\bsomething with food\b',        'something with protein or fat'),
        (r'\bespecially something with food\b', 'especially a meal with protein or fat'),
        # v7.9 후속: fat 과잉 — 문맥 붕괴 방지를 위해 food/meal 주변 치환 금지
        # "with fat" → 주변에 meal/food가 없을 때만 치환
        (r'\btaken?\s+with\s+fat\b',        'taken with food'),
        (r'\bsome fat\b',                   'a small meal'),
        (r'\bhigh.fat\b',                   'heavier'),
        (r'\bneeds?\s+fat\b',               'works best with food'),
        (r'\bwithout fat\b',                'on an empty stomach'),
        (r'\bgood fat\b',                   'healthy fats'),
        # v7.9: 음식명 치환 사고 복구 패턴 (almonds/avocado가 이미 치환된 경우)
        (r'\ba handful of a meal\b',        'a handful of almonds'),
        (r'\ba handful of a proper meal\b', 'a handful of almonds'),
        (r'\ba slice of a proper meal\b',   'a few slices of avocado'),
        (r'\bchew a few a meal\b',          'chew a few almonds'),
        (r'\byou needs food\b',             'your body needs fat'),
        (r'\byou needs\b',                  'you need'),
    ]
    changed = []
    for pattern, repl in replacements:
        new_html, n = re.subn(pattern, repl, html, flags=re.I)
        if n:
            changed.append(f"'{pattern}' → '{repl}' ({n}회)")
            html = new_html

    # v8.0: 치환 후 문장 붕괴 자동감지 & 복구
    # 1) 이중 관사 "a a " / "a an " / "an a "
    for _dbl in [(' a a ', ' a '), (' a an ', ' an '), (' an a ', ' an '), (' an an ', ' an ')]:
        if _dbl[0] in html:
            html = html.replace(_dbl[0], _dbl[1])
            changed.append(f"이중관사 수정: '{_dbl[0].strip()}'")
    # 2) 핵심 명사 단거리 이중 등장 (food/meal) — "a meal.*a proper meal" 등
    for _noun in ['meal', 'food']:
        html, _n = re.subn(
            rf'(a\s+(?:proper\s+|regular\s+|good\s+)?{_noun}\b[^.!?]{{0,40}})'
            rf'a\s+(?:proper\s+|regular\s+|good\s+)?{_noun}\b',
            rf'\1{_noun}',
            html, flags=re.I
        )
        if _n:
            changed.append(f"이중명사({_noun}) 수정 {_n}건")

    # v8.0: 누락된 문법 패턴
    _grammar_extra = [
        (r'\ba\s+help\b',           'support'),
        (r'\bgetting\s+a\s+help\b', 'getting support'),
        (r'\ba\s+instant\b',        'an instant'),   # 혹시 놓친 경우
        # v8.0 제거: That's → that's 는 문장 시작 대문자를 파괴하는 부작용 발생
        # 대신 하위 패턴으로만 처리 (구체적 케이스만)
        (r',\s+That\'s\b',   ", that's"),   # 콤마 뒤 중간 문장
        (r';\s+That\'s\b',   "; that's"),   # 세미콜론 뒤 중간 문장
    ]
    for pat, rep in _grammar_extra:
        new_html, n = re.subn(pat, rep, html, flags=re.I)
        if n:
            changed.append(f"문법 수정: '{pat}' → '{rep}' ({n}회)")
            html = new_html

    # v7.6: consistency 단어 3회 초과 시 추가 치환
    _consistency_count = len(re.findall(r'\bconsisten(?:t|cy|tly)\b', html, re.I))
    if _consistency_count > 2:
        html, n = re.subn(r'\bsticking with it consistently\b', 'sticking with it', html, flags=re.I)
        if n: changed.append(f"'sticking with it consistently' 과잉 ({n}회) → 단순화")
        html, n = re.subn(r'\bwith consistent use\b', 'with regular use', html, flags=re.I)
        if n: changed.append(f"'with consistent use' → 'with regular use' ({n}회)")
        html, n = re.subn(r'\bconsistent daily use\b', 'daily use', html, flags=re.I)
        if n: changed.append(f"'consistent daily use' → 'daily use' ({n}회)")
        html, n = re.subn(r'\bconsistently for\b', 'for', html, flags=re.I)
        if n: changed.append(f"'consistently for' → 'for' ({n}회)")

    # v7.6: og:description / body 내 AI 투 패턴 제거
    _desc_bads = [
        (r'\bthe mechanism,?\s+', ''),
        (r'\bmy honest timeline,?\s*', ''),
        (r'\b([A-Z][a-z]+) And ([A-Z][a-z]+)\b',       # "Citrulline And Malate" 등 And 대문자 패턴
         lambda m: m.group(1).lower() + ' and ' + m.group(2).lower()),
        (r'\bapparently for many others\b', 'others who tried the same approach'),
    ]
    for _pat, _rep in _desc_bads:
        html, n = re.subn(_pat, _rep, html, flags=re.I)
        if n: changed.append(f"AI투 패턴 제거: '{_pat}' ({n}회)")

    # v7.7: H2 소문자 시작 자동 수정 (H2 태그 + ToC 링크 텍스트 동시 처리)
    def _capitalize_h2(m):
        inner = m.group(2)
        if inner and inner[0].islower():
            inner = inner[0].upper() + inner[1:]
            changed.append(f'H2 소문자 시작 수정: {inner[:40]}')
        return m.group(1) + inner + m.group(3)
    html = re.sub(r'(<h2[^>]*>)([^<]+)(</h2>)', _capitalize_h2, html)

    # ToC 링크 텍스트도 동일하게 capitalize (H2와 동기화)
    # TOC: <a href="#secN" ...>소문자 시작 텍스트</a>
    def _capitalize_toc(m):
        text = m.group(2)
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
            changed.append(f'TOC 소문자 시작 수정: {text[:40]}')
        return m.group(1) + text + m.group(3)
    html = re.sub(r'(<a href="#sec\w+"[^>]*>)([^<]+)(</a>)', _capitalize_toc, html)

    # H2 반복 패턴 치환 (각인 수준 차단)
    _H2_BANNED = [
        (r'(<h2[^>]*>)(.*?)What Actually Changed(.*?)(</h2>)',
         lambda m: m.group(1) + m.group(2) + 'What I Noticed' + m.group(3) + m.group(4)),
        (r'(<h2[^>]*>)My Personal Protocol\s*:(.*?)(</h2>)',
         lambda m: m.group(1) + 'What Ended Up Working For Me' + m.group(3)),
        (r'(<h2[^>]*>)What Most People Get Wrong About This Nutrient(</h2>)',
         lambda m: m.group(1) + 'The Mistakes I Made Early On' + m.group(2)),
        (r'(<h2[^>]*>)How It Works in the Body(</h2>)',
         lambda m: m.group(1) + 'Why It Took Longer Than I Expected' + m.group(2)),
        # v7.6: "What I'd Tell Someone Starting Out" 사이트 전체 footprint 차단
        # dynamic_rules.json의 H2 pool에서 로테이션 (여기선 고정 대체)
        (r'(<h2[^>]*>)What I\'?d Tell Someone Starting Out(</h2>)',
         lambda m: m.group(1) + "The Part I Got Wrong" + m.group(2)),
    ]
    for pat, repl_fn in _H2_BANNED:
        new_html = re.sub(pat, repl_fn, html, flags=re.I | re.DOTALL)
        if new_html != html:
            changed.append(f'H2 반복패턴 치환: {pat[:40]}')
            html = new_html

    return html, changed


def _fix_opening_paragraph(html: str, title: str, ask_ai_fn) -> tuple[str, bool]:
    """오프닝 문단이 제목의 주제와 무관한 경우 AI로 재생성.

    감지 조건: 첫 번째 일반 <p>가 제목 키워드를 하나도 포함하지 않으면서
    동시에 'protein', 'carb', 'vitamin' 등 무관 보충제 단어로 시작하는 경우.
    """
    # hook(italic) 이후 첫 번째 실제 본문 <p> 추출
    # <p><em>...</em></p> 형태의 hook/disclosure 건너뜀
    body_p = re.findall(r'<p(?:\s[^>]*)?>(?!<em>)(.*?)</p>', html, re.I | re.DOTALL)
    if not body_p:
        return html, False

    first_body = body_p[0].lower()

    # 제목에서 주요 키워드 추출 (소문자, 2글자 이상 단어)
    title_keywords = set(w.lower() for w in re.findall(r'\b[a-z]{3,}\b', title.lower())
                         if w not in {'the','and','for','you','that','with','from','what',
                                      'why','how','when','your','this','into','felt','took',
                                      'week','four','until','useless','almost','quit','early',
                                      'changed','stopped','taking','randomly'})

    # 오프닝이 제목 키워드를 하나도 안 포함 + 무관 주제 단어 포함
    off_topic_triggers = ['protein', 'carbohydrate', 'carb ', 'calorie', 'vitamin b',
                          'vitamin c', 'vitamin d', 'omega-3', 'fish oil']
    has_title_word = any(kw in first_body for kw in title_keywords)
    is_off_topic   = any(t in first_body for t in off_topic_triggers)

    if has_title_word or not is_off_topic:
        return html, False  # 문제없음

    # 제목 기반 새 오프닝 생성
    new_opening = ""
    if ask_ai_fn:
        try:
            nutrient = re.sub(r'(?i)(felt useless|almost quit|what changed|why i|until week\s*\w+|'
                              r'complete guide|dosage guide|guide|:.*)', '', title).strip()
            new_opening = ask_ai_fn(
                f"Write a 3-sentence opening paragraph for a first-person supplement blog post titled:\n'{title}'\n"
                f"Subject: {nutrient}\n"
                "Rules: (1) Start with a direct personal observation about the supplement itself. "
                "(2) No protein/carb/unrelated supplement mentions. "
                "(3) Conversational, no hype. Output only the paragraph text.",
                "You are a personal health blogger. Output only the paragraph text.",
            ).strip()
        except Exception as e:
            log.warning(f"  [opening-fix] AI 생성 실패: {e}")

    if not new_opening or len(new_opening) < 80:
        nutrient = re.sub(r'(?i)(felt useless|almost quit|what changed|why i|until week\s*\w+|'
                          r'complete guide|dosage guide|guide|:.*)', '', title).strip()
        new_opening = (f"I expected {nutrient} to do something noticeable within the first week. "
                       f"It didn't. For almost three weeks I felt nothing — no better recovery, "
                       f"no reason to keep going. Then something shifted.")

    new_p = f"<p>{new_opening}</p>"

    # 첫 번째 본문 <p> 교체 (non-greedy, hook/em 건너뜀)
    html = re.sub(r'<p(?:\s[^>]*)?>(?!<em>)(.*?)</p>', new_p, html, count=1,
                  flags=re.I | re.DOTALL)
    log.info(f"  [opening-fix] 오프닝 교체: {new_opening[:80]}...")
    return html, True


def _fix_b1_og_desc(html: str, title: str, ask_ai_fn) -> tuple[str, str]:
    """og:description 재생성 및 HTML에 주입"""
    new_desc = ""
    if ask_ai_fn:
        try:
            new_desc = ask_ai_fn(
                f"Write a compelling meta description (120-155 characters) for a blog post titled:\n'{title}'\n"
                "Output only the description text. No quotes.",
                "You are an SEO copywriter. Output only the meta description.",
            ).strip()[:155]
        except Exception as e:
            log.warning(f"  og:description 재생성 실패: {e}")

    if not new_desc or len(new_desc) < 60:
        return html, ""

    import html as _htmllib
    desc_esc = _htmllib.escape(new_desc, quote=True)

    # og:description — 태그 전체 교체 (content 내 apostrophe 오작동 방지)
    _new_tag = f'<meta property="og:description" content="{desc_esc}"/>'
    html = re.sub(
        r'<meta[^>]*property=["\']og:description["\'][^/]*/?>',
        _new_tag, html, flags=re.I
    )
    # name="description" 도 동일 방식
    _new_name_tag = f'<meta name="description" content="{desc_esc}"/>'
    html = re.sub(
        r'<meta[^>]*name=["\']description["\'][^/]*/?>',
        _new_name_tag, html, flags=re.I
    )
    return html, new_desc


def _fix_b2_image(html: str, title: str) -> tuple[str, str]:
    """이미지 없을 때 Stability Matrix SD → 로컬 저장 → Imgur 업로드 (오케스트레이터 동일 방식).
    SD API 오프라인이면 Pollinations 다운로드 → 로컬 → Imgur.
    Imgur 실패 시 HTML 변경 없이 반환.
    """
    import base64 as _b64
    import requests as _req
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    BASE_DIR  = _Path(__file__).parent
    IMAGE_DIR = BASE_DIR / "05_Images"
    IMAGE_DIR.mkdir(exist_ok=True, parents=True)

    safe    = re.sub(r'[^\w]', '_', title)[:35]
    img_fn  = f"{safe}_hero_{_dt.now().strftime('%H%M%S')}.png"
    img_path = IMAGE_DIR / img_fn

    # ── 1. 이미지 생성: SD API → Pollinations 다운로드 폴백
    img_bytes = None
    try:
        from image_restorer import (
            try_sd15, try_pollinations, check_sd_api,
            build_hq_prompt, HERO_W, HERO_H,
        )
        prompt = build_hq_prompt(title, "hero")
        if check_sd_api():
            try:
                img_bytes = try_sd15(prompt, HERO_W, HERO_H, 25)
                log.info(f"    [B2] SD 생성 성공")
            except Exception as e:
                log.warning(f"    [B2] SD 실패 → Pollinations 다운로드: {e}")
        if img_bytes is None:
            img_bytes = try_pollinations(prompt, HERO_W, HERO_H)
            if img_bytes:
                log.info(f"    [B2] Pollinations 다운로드 완료 ({len(img_bytes)//1024}KB)")
    except Exception as e:
        log.warning(f"    [B2] 이미지 생성 실패: {e}")

    if not img_bytes:
        log.warning(f"    [B2] 이미지 생성 완전 실패 — 미삽입")
        return html, ""

    img_path.write_bytes(img_bytes)

    # ── 2. Imgur 업로드
    img_url = None
    try:
        b64_data = _b64.b64encode(img_bytes).decode()
        r = _req.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": b64_data, "type": "base64"},
            timeout=30,
        )
        if r.status_code == 200:
            img_url = r.json()["data"]["link"]
            log.info(f"    [B2] Imgur 업로드 완료: {img_url}")
        else:
            log.warning(f"    [B2] Imgur 응답 오류 {r.status_code} — 미삽입")
    except Exception as e:
        log.warning(f"    [B2] Imgur 업로드 실패 — 미삽입: {e}")

    if not img_url:
        return html, ""

    # ── 3. HTML 주입: hidden 썸네일(맨 앞) + hero 이미지(첫 </p> 뒤)
    alt_text = re.sub(r'["\']', '', title[:80])
    hidden_thumb = (
        f'<img src="{img_url}" style="display:none;width:1px;height:1px;" alt="" />\n'
    )
    img_block = (
        f'<p style="text-align:center;">'
        f'<img src="{img_url}" alt="{alt_text}" '
        f'style="max-width:100%;border-radius:8px;" /></p>\n'
    )

    if '<img' not in html:
        html = hidden_thumb + html
        first_p_end = re.search(r'</p>', html, re.I)
        if first_p_end:
            pos = first_p_end.end()
            html = html[:pos] + '\n' + img_block + html[pos:]
        else:
            html += img_block
    return html, img_url


def _fix_c1_hook(html: str, title: str, ask_ai_fn) -> tuple[str, str]:
    """Hook 없을 때 AI로 생성 또는 기본 Hook 주입"""
    hook_text = ""
    if ask_ai_fn:
        try:
            hook_text = ask_ai_fn(
                f"Write a compelling 2-sentence personal hook (italic intro) for a blog post titled:\n'{title}'\n"
                "Write in first person, conversational tone. Start with a personal anecdote or surprising fact. "
                "Output only the hook text (90-150 characters). No quotes.",
                "You are a personal health blogger. Write only the hook text.",
            ).strip()[:400]
        except Exception as e:
            log.warning(f"  Hook AI 생성 실패: {e}")

    if not hook_text or len(hook_text) < 60:
        nutrient = re.sub(r'(?i)(complete guide|dosage guide|guide|:.*)', '', title).strip()
        hook_text = (
            f"I didn't expect {nutrient} to make such a measurable difference — "
            f"but after months of testing, the data was hard to argue with. "
            f"Here's exactly what I found."
        )

    hook_block = f'<hr />\n<p><em>{hook_text}</em></p>\n<hr />\n'

    # 첫 번째 <p> 앞에 삽입
    first_p = re.search(r'<p[^>]*>', html, re.I)
    if first_p:
        html = html[:first_p.start()] + hook_block + html[first_p.start():]
    else:
        html = hook_block + html
    return html, hook_text


def _check_and_fix_metadata(html: str, blogger_title: str) -> tuple[str, list, list]:
    """
    v8.0 메타데이터 일관성 체크 + 자동수정
    체크 항목:
      1. OG Title = H1 = JSON-LD headline 일치
      2. OG Description = JSON-LD Description = JS desc 일치 (apostrophe-safe)
      3. Complete 흔적 없음 (H1/OG title/JSON-LD)
      4. Dosage Guide 흔적 없음
      5. Alt 텍스트 이상 패턴
      6. 문장 시작 소문자 (<p> 또는 " 직후)
      7. 치환 사고 흔적 (이중 단어, 합쳐진 문장)
    Returns: (fixed_html, ok_list, warn_list)
    """
    ok   = []
    warn = []
    fixed = []

    # ── 헬퍼 ────────────────────────────────────────────────────
    def get(pattern, flags=re.I): return re.search(pattern, html, flags)

    # ── 1. 제목 3곳 일치 확인 ────────────────────────────────────
    h1_m    = get(r'<h1[^>]*>(.*?)</h1>', re.I|re.S)
    ogt_m   = get(r'property=["\']og:title["\'][^>]*content="([^"]+)"')
    jld_m   = get(r'"headline"\s*:\s*"([^"]+)"')
    h1      = re.sub(r'<[^>]+>','',h1_m.group(1)).strip() if h1_m else ''
    og_t    = ogt_m.group(1).strip() if ogt_m else ''
    jld_hl  = jld_m.group(1).strip() if jld_m else ''

    title_ok = (h1 == og_t == jld_hl == blogger_title)
    if title_ok:
        ok.append("✅ OG Title = H1 = JSON-LD headline 일치")
    else:
        warn.append(f"❌ 제목 불일치\n     Blogger : {blogger_title[:60]}\n     H1      : {h1[:60]}\n     OG title: {og_t[:60]}\n     JSON-LD : {jld_hl[:60]}")
        # 자동 수정: 전부 blogger_title로 통일
        html = re.sub(r'(<h1[^>]*>)[^<]*(</h1>)',
                      lambda m: m.group(1)+blogger_title+m.group(2), html, flags=re.I)
        for pat in [r'(property=["\']og:title["\'][^>]*content=")[^"]+(")',
                    r'(content=")[^"]+("[^>]*property=["\']og:title["\'])'  ]:
            html = re.sub(pat, lambda m: m.group(1)+blogger_title+m.group(2), html, flags=re.I)
        html = re.sub(r'("headline"\s*:\s*")[^"]+(")',
                      lambda m: m.group(1)+blogger_title+m.group(2), html)
        fixed.append(f"제목 4곳 → '{blogger_title[:50]}'")

    # ── 2. Description 3곳 일치 + apostrophe-safe ─────────────────
    ogd_m  = get(r'property=["\']og:description["\'][^>]*content="([^"]+)"')
    jldd_m = get(r'"description"\s*:\s*"([^"]+)"')
    jsd_m  = get(r'var\s+desc\s*=\s*"([^"]+)"')
    og_d   = ogd_m.group(1)  if ogd_m  else ''
    jld_d  = jldd_m.group(1) if jldd_m else ''
    js_d   = jsd_m.group(1)  if jsd_m  else ''

    desc_ok = (og_d == jld_d == js_d) and og_d
    # 합쳐진 문장 감지: description에 두 버전이 붙어있는 패턴
    desc_merged = len(og_d) > 200 or (og_d and og_d.count('. ') > 3)
    if desc_ok and not desc_merged:
        ok.append(f"✅ OG/JSON-LD/JS Description 일치 ({len(og_d)}자)")
    else:
        if desc_merged:
            warn.append(f"❌ Description 합쳐짐 감지 ({len(og_d)}자) — 수동 확인 필요:\n     {og_d[:120]}")
        else:
            warn.append(f"❌ Description 3곳 불일치\n     OG    : {og_d[:80]}\n     JSON-LD: {jld_d[:80]}\n     JS    : {js_d[:80]}")
            # 자동 수정: OG → JSON-LD, JS
            if og_d:
                html = re.sub(r'("description"\s*:\s*")[^"]+(")',
                              lambda m: m.group(1)+og_d+m.group(2), html)
                html = re.sub(r'var\s+desc\s*=\s*"[^"]*(?:\'[^"]*)*";',
                              f'var desc = "{og_d}";', html)
                fixed.append("JSON-LD desc + JS var desc → OG desc로 동기화")

    # ── 3. Complete 흔적 ──────────────────────────────────────────
    complete_hits = re.findall(r'\bComplete\b(?!\s+Guide\s+(?:for|to|on)|\s+(?:list|set|pack))', h1+og_t+jld_hl, re.I)
    if complete_hits:
        warn.append(f"❌ 제목에 'Complete' 흔적: {complete_hits}")
    else:
        ok.append("✅ Complete 흔적 없음")

    # ── 4. Dosage Guide 흔적 ─────────────────────────────────────
    dosage_hits = re.findall(r'Dosage\s+Guide|How\s+Much\s+Do\s+You\s+Need', h1+og_t+jld_hl, re.I)
    if dosage_hits:
        warn.append(f"❌ 'Dosage Guide' 흔적: {dosage_hits}")
    else:
        ok.append("✅ Dosage Guide 흔적 없음")

    # ── 5. Alt 텍스트 이상 패턴 ──────────────────────────────────
    alts = re.findall(r'alt="([^"]*)"', html, re.I)
    bad_alts = [a for a in alts if re.search(
        r'\bcomplete\b|\band complete\b|automation|webdriver|documentation|^[\w-]+$',
        a, re.I
    )]
    if bad_alts:
        warn.append(f"❌ 이상한 Alt 텍스트: {bad_alts[:3]}")
    else:
        ok.append(f"✅ Alt 텍스트 정상 ({len(alts)}개)")

    # ── 6. 문장 시작 소문자 ──────────────────────────────────────
    p_starts = re.findall(r'<p[^>]*>([a-z][^<]{0,30})', html)
    q_starts = re.findall(r'"([a-z][^"]{0,20})', html)  # 따옴표 뒤 소문자
    bad_caps = [s for s in p_starts if s[0].islower() and len(s) > 3][:5]
    if bad_caps:
        warn.append(f"❌ 문장 시작 소문자 {len(bad_caps)}개: {bad_caps}")
        # 자동 수정: <p> 태그 직후 소문자 → 대문자
        html = re.sub(r'(<p[^>]*>)([a-z])',
                      lambda m: m.group(1)+m.group(2).upper(), html)
        fixed.append(f"<p> 시작 소문자 자동 대문자화")
    else:
        ok.append("✅ 문장 시작 대소문자 정상")

    # ── 7. 치환 사고 흔적 ────────────────────────────────────────
    subs_accidents = []
    # 이중 단어
    for noun in ['meal','food','morning','morning']:
        if re.search(rf'\b{noun}\b[^.!?]{{0,30}}\b{noun}\b', html, re.I):
            subs_accidents.append(f"'{noun}' 이중 등장")
    # 합쳐진 description 흔적
    if re.search(r"going\.'d been|enough\.'d been|notice\.'d been", html):
        subs_accidents.append("Description 합쳐짐 흔적")
    # "in the mornings in the morning"
    if re.search(r'in the mornings? in the mornings?', html, re.I):
        subs_accidents.append("'in the mornings' 중복")
        html = re.sub(r'in the mornings? in the mornings?', 'in the mornings', html, flags=re.I)
        fixed.append("'in the mornings in the morning' 중복 제거")

    if subs_accidents:
        warn.append(f"❌ 치환 사고 흔적: {subs_accidents}")
    else:
        ok.append("✅ 치환 사고 흔적 없음")

    # ── 로그 출력 ─────────────────────────────────────────────────
    log.info("  [MetaCheck] ── 메타데이터 일관성 검사 ──")
    for o in ok:   log.info(f"  [MetaCheck] {o}")
    for w in warn: log.warning(f"  [MetaCheck] {w}")
    if fixed:
        for f_ in fixed: log.info(f"  [MetaCheck] 자동수정: {f_}")

    return html, ok, warn


def _fix_d4_html_bugs(html: str) -> tuple[str, list]:
    """반복되는 HTML 구조 버그 자동 수정:
    1. &amp;#숫자; 이중인코딩 → 디코딩
    2. &#8594; 엔티티 잔존 → → 직접 텍스트
    3. DOCTYPE 전체문서 → body 내용 추출 (orchestrator의 _strip_html_document_wrapper와 동일)
    """
    import html as _html_lib
    fixed = []

    # 1. 이중인코딩 해제
    if re.search(r'&amp;#\d+;', html):
        html = _html_lib.unescape(html)
        fixed.append("&amp;# 이중인코딩 해제")

    # 2. &#8594; 엔티티 → → 직접 삽입
    if '&#8594;' in html:
        html = html.replace('&#8594;', '→')
        fixed.append("&#8594; → → 교체")

    # 3. TOC CSS content 속성의 → 제거 (리터럴 텍스트 노출 방지)
    html = re.sub(r'content:\s*["\']?&#8594;["\']?', '', html)

    # 4. DOCTYPE 전체문서 → body 추출
    if html.strip().startswith('<!DOCTYPE') or html.strip().startswith('<html'):
        body_m = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.I)
        if body_m:
            html = body_m.group(1).strip()
            fixed.append("DOCTYPE 전체문서 → body 내용 추출")

    # 5. og:description / meta description 중복 텍스트 제거
    # "Six months on Six months on B12" 같은 이중 접두어 패턴
    def _dedup_og(m):
        val = m.group(2)
        # "X X Y" → "X Y" (앞 단어 덩어리가 반복되면 한 번만)
        deduped = re.sub(r'^(.{10,60}?)\s+\1', r'\1', val)
        if deduped != val:
            fixed.append(f"og:description 중복 제거: '{val[:50]}'")
            return m.group(1) + deduped + m.group(3)
        return m.group(0)
    html = re.sub(
        r'(content=")([^"]{20,})(")',
        _dedup_og, html, flags=re.I
    )

    # 연속 이중 <hr> 태그 → 하나로 합침
    new_html_hr, n_hr = re.subn(
        r'(<hr\s*/?>\s*)+(<hr\s*/?>)', r'\2', html, flags=re.I
    )
    if n_hr:
        html = new_html_hr
        fixed.append(f"이중 <hr> 태그 제거 ({n_hr}곳)")

    # 6-b. <p>/<li>/<dd> 시작 소문자 영양소명 자동 대문자
    _nutrient_caps = ["zinc","magnesium","iron","calcium","selenium","copper",
                      "chromium","iodine","boron","manganese","molybdenum",
                      "hmb","nmn","same","coq10","pqq","nad"]
    for nt in _nutrient_caps:
        new_html_nt, n_nt = re.subn(
            rf'(<(?:p|li|dd|dt)>){nt}\b',
            lambda m, cap=nt: m.group(1) + cap.upper(),
            html, flags=re.I
        )
        if n_nt:
            html = new_html_nt
            fixed.append(f"<p> 시작 소문자 {nt} → 대문자 ({n_nt}건)")

    # 6-a. JS var desc → og:description 동기화 (apostrophe-safe 세미콜론 기준)
    og_m = re.search(r'og:description[^>]+content="([^"]+)"', html, re.I)
    if og_m:
        og_desc = og_m.group(1)
        has_var_desc = bool(re.search(r'var\s+desc\s*=', html, re.I))
        if not has_var_desc:
            # var desc 없으면 <h1> 앞에 자동 주입
            _script = f'<script type="text/javascript">\nvar desc = "{og_desc}";\n</script>\n'
            if '<h1' in html:
                html = html.replace('<h1', _script + '<h1', 1)
            fixed.append("JS var desc 없음 → <h1> 앞에 자동 주입")
        else:
            # var desc = "..."; 전체를 세미콜론까지 교체
            new_html_vd, n_vd = re.subn(
                r'var\s+desc\s*=\s*"[^;]+"(?=\s*;)',
                f'var desc = "{og_desc}"',
                html, flags=re.I
            )
            if n_vd and new_html_vd != html:
                html = new_html_vd
                fixed.append(f"JS var desc → og:description 동기화 ({n_vd}건)")

    # 6-b. JSON-LD "description" → og:description 동기화 (v8.0)
    if og_m:
        og_desc = og_m.group(1)
        new_html_jld, n_jld = re.subn(
            r'("description"\s*:\s*")[^"]+(")',
            rf'\g<1>{og_desc}\2',
            html
        )
        if n_jld and new_html_jld != html:
            html = new_html_jld
            fixed.append(f"JSON-LD description → og:description 동기화 ({n_jld}건)")

    # 6. <script> 내 한국어 포함 JS 주석 제거 (영어 주석만 유지)
    def _strip_korean_js_comments(m):
        block = m.group(0)
        cleaned = re.sub(r'//[^\n]*[가-힣][^\n]*', '', block)
        return cleaned

    new_html_js = re.sub(r'<script[^>]*>.*?</script>', _strip_korean_js_comments,
                         html, flags=re.DOTALL | re.I)
    if new_html_js != html:
        html = new_html_js
        fixed.append("JS 한국어 주석 제거")

    return html, fixed


def _fix_a1_complete_guide(html: str, title: str) -> tuple[str, str]:
    """H1에서 'Complete Guide' / 'Complete' 제거. 제목은 HTML과 독립적으로 항상 수정."""
    fixed_title = title
    patterns = [
        (r'\s*Complete Guide\s*:', ':'),
        (r'\s*Complete Guide\b', ''),
        (r':\s*Complete\b', ':'),
        (r'\s+Complete\s*:', ':'),   # "Creatine Complete:" → "Creatine:"
    ]
    new_html = html

    # HTML H1 수정 — HTML 안에 패턴이 있을 때만
    for pattern, repl in patterns:
        if re.search(pattern, new_html, re.I):
            new_html = re.sub(
                r'(<h1[^>]*>)(.*?)(</h1>)',
                lambda m, p=pattern, r=repl: (
                    m.group(1) + re.sub(p, r, m.group(2), flags=re.I) + m.group(3)
                ),
                new_html, flags=re.I | re.DOTALL
            )

    # Blogger 제목 수정 — HTML과 무관하게 항상 적용
    for pattern, repl in patterns:
        fixed_title = re.sub(pattern, repl, fixed_title, flags=re.I).strip()

    return new_html, fixed_title.strip()


_A1_BAD_TITLE_STRIP = [
    # v7.6: "Dosage Guide" / "How Much Do You Need" 패턴
    (r'\s*:?\s*Dosage Guide\b.*$',               ''),
    (r'\s*:?\s*How Much Do You Need.*$',          ''),
    # v7.6: ": Guide to X and Y" — Vitamin D3 회귀 패턴
    (r'\s*:\s*Guide to\s+[\w\s]+and\s+[\w\s]+$', ''),
    # ": Guide to dosage" 단독
    (r'\s*:\s*Guide to dosage.*$',                ''),
    # 콜론 뒤 "Is X Worth Taking?" 패턴 (앞에 영양소명 있는 경우)
    (r'\s*:\s*Is\s+\w[\w\s]+Worth Taking\?.*$', ''),
    # "What the Research Says" / "Research Says" 뒤 제거
    (r'\s*:?\s*What the Research Says.*$',      ''),
    (r'\s*Worth Taking\?.*$',                   ''),
    # "What X Research Says" 변형
    (r'\s*What\s+\w+\s+Research\s+Says.*$',     ''),
    # 후미 "Complete" 단독 잔재
    (r'\s+Complete$',                            ''),
    (r':\s*Complete$',                           ''),
]

# 영양소명 포함 템플릿 — {nutrient} 자리에 자동 삽입
_A1_TITLE_TEMPLATES = [
    "The {nutrient} Mistake That Delayed My Results",
    "Why My {nutrient} Routine Wasn't Working",
    "I Took {nutrient} Wrong for Months",
    "What Six Weeks on {nutrient} Actually Taught Me",
    "The {nutrient} Mistake I Kept Making",
]


def _extract_nutrient_from_title(title: str) -> str:
    """제목에서 영양소명 추출. 'Is X Worth Taking?' 등 패턴 처리."""
    # "Is Vitamin B12 Worth Taking?" → "Vitamin B12"
    m = re.search(r'^Is\s+([\w\s\-]+?)\s+Worth Taking', title, re.I)
    if m:
        return m.group(1).strip()
    # "Vitamin B12 Complete: Is..." → "Vitamin B12"
    m = re.search(r'^([\w\s\-]+?)\s+Complete\s*:', title, re.I)
    if m:
        return m.group(1).strip()
    # "X Complete Guide" → "X"
    m = re.search(r'^([\w\s\-]+?)\s+Complete Guide', title, re.I)
    if m:
        return m.group(1).strip()
    return ""


def _fix_a1_bad_title(html: str, title: str, ask_ai_fn=None) -> tuple[str, str]:
    """
    A1 점수 5점 미만 제목 자동 수정.
    1. 영양소명 먼저 추출 (나쁜 패턴 제거 전)
    2. 나쁜 패턴 strip
    3. 남은 제목이 너무 짧으면 → AI 또는 영양소명 포함 템플릿으로 보완
    4. H1 + og:title + JSON-LD headline 동시 수정
    """
    fixed_title = title

    # Step 0 — 영양소명 미리 추출 (strip 전에 해야 정확함)
    nutrient_hint = _extract_nutrient_from_title(title)

    # Step 1 — 나쁜 패턴 제거
    # "Is X Worth Taking?" 전체 제목인 경우 → 영양소명만 남김
    if re.match(r'^Is\s+\w[\w\s]+Worth Taking', fixed_title, re.I):
        fixed_title = nutrient_hint or re.sub(
            r'^Is\s+([\w\s\-]+?)\s+Worth Taking.*$', r'\1', fixed_title, flags=re.I
        ).strip()
    else:
        for pattern, repl in _A1_BAD_TITLE_STRIP:
            fixed_title = re.sub(pattern, repl, fixed_title, flags=re.I).strip()

    # Complete Guide / Complete 제거
    for pattern, repl in [
        (r'\s*Complete Guide\s*:', ':'), (r'\s*Complete Guide\b', ''),
        (r':\s*Complete\b', ':'),        (r'\s+Complete\s*:', ':'),
    ]:
        fixed_title = re.sub(pattern, repl, fixed_title, flags=re.I).strip()

    if fixed_title == title:
        return html, title  # 변경 없음

    # Step 2 — 남은 제목이 너무 짧으면 보완
    if len(fixed_title) < 25:
        # 영양소명: strip된 결과 또는 미리 추출한 hint 사용
        nutrient = (fixed_title.strip(': ').strip() or nutrient_hint).strip()

        if ask_ai_fn and nutrient:
            try:
                new_title = ask_ai_fn(
                    f"Write a personal blog post title about {nutrient} supplementation.\n"
                    "Rules: first-person experience tone, 40-65 chars, NO 'Complete Guide', "
                    "NO 'Worth Taking', NO 'Research Says'.\n"
                    "Example style: 'The Berberine Mistake That Made Me Want to Quit'\n"
                    "Output only the title.",
                    "You are a personal health blogger. Output only the title, no quotes.",
                ).strip().strip('"').strip("'")
                if 30 <= len(new_title) <= 80 and new_title != title:
                    fixed_title = new_title
                    log.info(f"    [A1-fix] AI 제목 생성: '{fixed_title}'")
            except Exception as e:
                log.warning(f"    [A1-fix] AI 제목 생성 실패: {e}")

        if len(fixed_title) < 25:
            import random
            template = random.choice(_A1_TITLE_TEMPLATES)
            if nutrient:
                fixed_title = template.replace("{nutrient}", nutrient)
            else:
                fixed_title = template.replace("{nutrient} ", "").replace("{nutrient}", "supplement")
            log.info(f"    [A1-fix] 템플릿 제목: '{fixed_title}'")

    # Step 3 — HTML 수정 (H1 + og:title + JSON-LD)
    new_html = html
    # H1
    new_html = re.sub(
        r'(<h1[^>]*>)[^<]*(</h1>)',
        lambda m: m.group(1) + fixed_title + m.group(2),
        new_html, flags=re.I
    )
    # og:title (양쪽 속성 순서 처리)
    new_html = re.sub(
        r'(property="og:title"[^>]+content=")[^"]*(")',
        lambda m: m.group(1) + fixed_title + m.group(2),
        new_html, flags=re.I
    )
    new_html = re.sub(
        r'(content=")[^"]*("[^>]+property="og:title")',
        lambda m: m.group(1) + fixed_title + m.group(2),
        new_html, flags=re.I
    )
    # JSON-LD headline
    new_html = re.sub(
        r'("headline"\s*:\s*")[^"]*(")',
        lambda m: m.group(1) + fixed_title + m.group(2),
        new_html, flags=re.I
    )
    log.info(f"    [A1-fix] 제목 수정: '{title[:50]}' → '{fixed_title[:60]}'")
    return new_html, fixed_title


def _fix_b1_og_desc_korean(html: str) -> tuple[str, str]:
    """og:description 한국어 혼입 감지 — 자동 수정 불가, note만 반환"""
    og = re.search(r'(<meta[^>]+property="og:description"[^>]+content=")([^"]+)(")', html, re.I)
    if og and re.search(r'[가-힣]', og.group(2)):
        return html, f"한국어 혼입 감지: '{og.group(2)[:60]}' — 수동 교체 필요"
    return html, ""


_CLOSING_SECTION_FORMATS = [
    "⚡ Key Takeaways",
    "What surprised me most:",
    "My biggest takeaway:",
    "Would I take it again? Here's what I learned:",
    "What I'd tell myself before starting:",
    "My honest summary:",
]

_CLOSING_SECTION_PROMPT = """This blog post is titled: "{title}"

Write a short closing section (4–6 bullet points) written in first-person experience voice.

Section heading to use: "{heading}"

Rules:
- Write from personal experience — what actually changed, when, how it felt
- NO generic advice like "start with a low dose", "consult your doctor", "combine with other nutrients"
- NO fat absorption mentions unless the supplement is fat-soluble (vitamins D, K, E, A, CoQ10)
- Include at least one uncertain or imperfect observation ("I'm still not 100% sure if...", "the changes were gradual, not dramatic")
- Each bullet should be a distinct observation, not a rephrasing of the same point

Return ONLY the HTML block, no explanation:
<div style="background:#f0f7ff;border-left:4px solid #4a90d9;padding:16px 20px;margin:28px 0;border-radius:4px;">
<h2 style="margin-top:0;">{heading}</h2>
<ul>
<li>...</li>
</ul>
</div>"""


def _fix_d3_missing_elements(html: str, title: str, ask_ai_fn=None) -> tuple[str, list]:
    """Takeaways 누락 시 자동 주입 (hook/img는 B2/C1에서 처리)"""
    injected = []

    # Takeaways 없으면 주입
    if not re.search(
        r'takeaway|key.take|what i.d tell|my verdict|what i learned|key lesson'
        r'|what surprised|biggest takeaway|honest summary|would i take',
        html, re.I):
        closing_html = ""

        # AI로 포스팅 맞춤 클로징 섹션 생성
        if ask_ai_fn:
            try:
                import random
                heading = random.choice(_CLOSING_SECTION_FORMATS)
                prompt = _CLOSING_SECTION_PROMPT.replace("{title}", title).replace("{heading}", heading)
                raw = ask_ai_fn(prompt, "You are a personal health blogger. Return only the HTML div block.")
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-z]*\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw).strip()
                if "<div" in raw and "<li>" in raw and len(raw) > 100:
                    closing_html = "\n" + raw + "\n"
                    log.info(f"  [D3] AI 클로징 섹션 생성 완료: {heading}")
            except Exception as e:
                log.warning(f"  [D3] AI 클로징 생성 실패: {e}")

        # 폴백: 최소한의 경험 기반 기본 템플릿
        if not closing_html:
            nutrient = re.sub(r'(?i)(complete guide|dosage guide|guide|:.*)', '', title).strip()
            closing_html = (
                f'\n<div style="background:#f0f7ff;border-left:4px solid #4a90d9;'
                f'padding:16px 20px;margin:28px 0;border-radius:4px;">\n'
                f'<h2 style="margin-top:0;">⚡ Key Takeaways</h2>\n<ul>\n'
                f'<li>The changes were gradual — I noticed more after <strong>week 4</strong> than the first few weeks</li>\n'
                f'<li>Consistency mattered more than perfect timing</li>\n'
                f'<li>Results were real but subtle — not dramatic</li>\n'
                f'<li>I\'m still not 100% sure how much was {nutrient} vs other habit changes</li>\n'
                f'</ul>\n</div>\n'
            )
        disclosure = re.search(r'<div[^>]+class="[^"]*disclosure[^"]*"', html, re.I)
        if disclosure:
            html = html[:disclosure.start()] + closing_html + html[disclosure.start():]
        elif '</body>' in html:
            html = html.replace('</body>', closing_html + '</body>', 1)
        else:
            html += closing_html
        injected.append("takeaways")

    # Disclosure 없으면 주입
    if not re.search(r'disclosure|affiliate', html, re.I):
        disc = (
            '\n<div class="disclosure" style="background:#f9f9f9;border-left:4px solid #ccc;'
            'padding:12px 16px;margin:20px 0;font-size:0.85em;">'
            '<strong>Disclosure:</strong> This post contains affiliate links. '
            'We may earn a commission at no extra cost to you.</div>\n'
        )
        html += disc
        injected.append("disclosure")

    return html, injected


def _generate_labels(title: str) -> list:
    """제목에서 토픽 라벨 자동 생성 (최대 15개)"""
    BRAND = ["NutriStackLab", "NordicHealth", "Supplements", "VitaminsAndMinerals"]

    # 영양소 식별자 (D3, K2, B12, MK7 등)
    identifiers = re.findall(r'\b[A-Z]{1,3}\d+(?:-\d+)?\b', title)

    # 핵심 단어 (3자 이상, stop 제거)
    stop = {"the","and","or","a","an","of","for","in","with","vs","is","your",
            "how","why","complete","guide","dosage","when","what","does","do",
            "my","i","me","its","are","to","all","about","best","top","can"}
    words = [w for w in re.findall(r'\b[A-Za-z]{3,}\b', title) if w.lower() not in stop]

    # CamelCase 변환
    word_labels = [w[0].upper() + w[1:] for w in dict.fromkeys(words)]

    # 복합 라벨: "Vitamin D3" → "VitaminD3"
    compound = re.findall(r'\b(Vitamin\s+[A-Z]\d*(?:\s+\([^)]+\))?)\b', title, re.I)
    compound_labels = [re.sub(r'\s+', '', c.title()) for c in compound]

    all_labels = list(dict.fromkeys(BRAND + compound_labels + identifiers + word_labels))
    return all_labels[:15]


def _fix_d2_internal_links(html: str, title: str, links_db_path: Path) -> tuple[str, list]:
    """시너지 기반 내부 링크 2-4개 주입"""
    if not links_db_path or not links_db_path.exists():
        return html, []
    try:
        links = json.loads(links_db_path.read_text(encoding="utf-8"))
    except Exception:
        return html, []

    # ── 시너지 맵: 영양소 → 관련 영양소 목록 ────────────────────────────
    SYNERGY_MAP: dict[str, list[str]] = {
        "copper":     ["zinc", "iron", "vitamin c", "selenium"],
        "zinc":       ["copper", "vitamin c", "selenium", "magnesium"],
        "iron":       ["vitamin c", "copper", "b12", "folate"],
        "magnesium":  ["vitamin d", "zinc", "b6", "calcium"],
        "vitamin d":  ["magnesium", "vitamin k2", "zinc", "calcium"],
        "vitamin k2": ["vitamin d", "magnesium", "calcium"],
        "vitamin c":  ["iron", "zinc", "collagen", "copper"],
        "selenium":   ["zinc", "vitamin e", "iodine", "copper"],
        "vitamin b12":["folate", "b6", "iron", "same"],
        "b12":        ["folate", "b6", "iron", "same"],
        "nmn":        ["resveratrol", "coq10", "nad"],
        "melatonin":  ["magnesium", "5-htp", "b6"],
        "same":       ["b12", "folate", "magnesium"],
        "berberine":  ["chromium", "magnesium", "zinc"],
        "probiotics": ["vitamin d", "zinc", "magnesium"],
        "hmb":        ["creatine", "vitamin d", "protein"],
        "creatine":   ["hmb", "magnesium", "vitamin d"],
        "citrulline": ["arginine", "beet", "magnesium"],
        "taurine":    ["magnesium", "b6", "zinc"],
        "glutathione":["vitamin c", "selenium", "nac"],
        "niacin":     ["b12", "b6", "folate"],
        "collagen":   ["vitamin c", "zinc", "silicon"],
        "coq10":      ["nmn", "vitamin e", "magnesium"],
        "omega":      ["vitamin d", "vitamin e", "magnesium"],
        "ashwagandha":["magnesium", "zinc", "b6"],
        "vitamin e":  ["selenium", "coq10", "vitamin c"],
    }

    # ── 포스팅 제목에서 영양소명 추출 ────────────────────────────────────
    title_lower = title.lower()
    matched_nutrient = None
    for nutrient in SYNERGY_MAP:
        if nutrient in title_lower:
            matched_nutrient = nutrient
            break

    # ── 1순위: 시너지 파트너 포스팅 ─────────────────────────────────────
    candidates = []
    if matched_nutrient:
        partners = SYNERGY_MAP[matched_nutrient]
        for lnk in links:
            lnk_title = lnk.get("title", "").lower()
            lnk_url   = lnk.get("url", "")
            if not lnk_url or matched_nutrient in lnk_title:
                continue  # 자기 자신 제외
            # 파트너 영양소가 제목에 있으면 점수
            synergy_score = sum(
                (len(partners) - i)  # 앞에 나올수록 높은 점수
                for i, p in enumerate(partners)
                if p in lnk_title
            )
            if synergy_score > 0:
                candidates.append((synergy_score, lnk_url, lnk.get("title", "")))

    # ── 2순위: 제목 키워드 매칭 (시너지 매칭 부족 시 보충) ───────────────
    if len(candidates) < 2:
        stop = {"and","the","a","an","of","for","to","in","is","are","with",
                "how","when","what","why","does","do","my","i","me","its","vs",
                "it","took","taking","started","after","almost","quit","work",
                "until","week","month","every","day","what","didn","here","wrong"}
        kws = [w.lower() for w in re.findall(r'\b[A-Za-z]{4,}\b', title)
               if w.lower() not in stop]
        existing_urls = {url for _, url, _ in candidates}
        for lnk in links:
            lnk_title = lnk.get("title", "").lower()
            lnk_url   = lnk.get("url", "")
            if not lnk_url or lnk_url in existing_urls:
                continue
            if matched_nutrient and matched_nutrient in lnk_title:
                continue  # 같은 영양소 자기 자신류 제외
            kw_score = sum(1 for k in kws if k in lnk_title)
            if kw_score > 0:
                candidates.append((kw_score * 0.5, lnk_url, lnk.get("title", "")))

    candidates.sort(reverse=True)
    chosen = candidates[:4]

    # ── 3순위: 그래도 없으면 최신 2개 ───────────────────────────────────
    if not chosen:
        chosen = [(0, lnk.get("url", ""), lnk.get("title", ""))
                  for lnk in reversed(links[-4:]) if lnk.get("url")
                  and (matched_nutrient or "") not in lnk.get("title","").lower()][:2]
    if not chosen:
        return html, []

    log.info(
        f"  [D2] 시너지링크 {'매칭(' + matched_nutrient + ')' if matched_nutrient else '키워드매칭'}: "
        f"{[t[:30] for _,_,t in chosen]}"
    )

    link_parts = [f'<a href="{url}">{t[:55]}</a>' for _, url, t in chosen if url]
    link_block = (
        '<p style="font-size:0.9em;color:#555;margin-top:20px;">'
        'Related reading: ' + " | ".join(link_parts) + '</p>'
    )

    if 'class="disclosure"' in html:
        html = html.replace('<div class="disclosure">', link_block + '\n<div class="disclosure">', 1)
    else:
        html += "\n" + link_block

    injected = [t[:55] for _, _, t in chosen]
    return html, injected


# ── 레슨 / Hermes 큐 기록 ─────────────────────────────────────────────────────

def _record_lesson(meta_dir: Path, cat: str, note: str, title: str, score: int):
    """agent_lessons.json에 실패 항목 기록"""
    lessons_path = meta_dir / "agent_lessons.json"
    try:
        lessons = json.loads(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else {}
    except Exception:
        lessons = {}

    agent_key = AGENT_ROUTING.get(cat, "03_Writer_Gardener") if _QC_AVAILABLE else "03_Writer_Gardener"
    label     = CATEGORY_LABELS.get(cat, cat) if _QC_AVAILABLE else cat
    today     = datetime.now().strftime("%Y-%m-%d")
    lesson_text = f"[발행후검증-{cat}] {label} {score}/10 — {note} | {title[:40]}"

    agent_lessons = lessons.setdefault(agent_key, [])
    existing = next((e for e in agent_lessons
                     if e.get("cat") == cat and e.get("topic", "") == title[:40]), None)
    if existing:
        existing["count"] = existing.get("count", 1) + 1
        existing["date"]  = today
        existing["score"] = score
        existing["note"]  = note
        count = existing["count"]
    else:
        agent_lessons.append({
            "date": today, "cat": cat, "topic": title[:40],
            "lesson": lesson_text, "score": score, "note": note,
            "count": 1, "first_seen": today,
        })
        count = 1

    try:
        lessons_path.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"  레슨 저장 실패: {e}")
    return count


def _push_hermes_queue(meta_dir: Path, items: list):
    """hermes_queue.json에 즉시 에스컬레이션 항목 추가"""
    queue_path = meta_dir / "hermes_queue.json"
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    except Exception:
        queue = []

    TERMINAL = {"exhausted", "done"}
    for item in items:
        existing = next((q for q in queue
                         if q.get("cat") == item["cat"] and q.get("post_id") == item.get("post_id")), None)
        if existing:
            if existing.get("status") in TERMINAL:
                log.info(f"  [Hermes 큐] {item['cat']} 이미 {existing['status']} — 재큐 스킵")
                continue
            existing.update({k: v for k, v in item.items() if k != "retry_count"})
            existing["status"] = "pending"
        else:
            item["status"] = "pending"
            item.setdefault("retry_count", 0)
            queue.append(item)

    try:
        queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"  Hermes 큐 저장 실패: {e}")


# ── Claude 발견 학습 루프 ─────────────────────────────────────────────────────

_DISCOVERIES_FILE = None   # lazy-init in _learn_from_scan()

def _get_discoveries_path(meta_dir: Path) -> Path:
    return meta_dir / "claude_discoveries.json"

def _load_discoveries(meta_dir: Path) -> list:
    p = _get_discoveries_path(meta_dir)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_discoveries(meta_dir: Path, data: list):
    p = _get_discoveries_path(meta_dir)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _promote_to_dynamic_rules(meta_dir: Path, rule_text: str):
    """dynamic_rules.json에 규칙 추가 (오케스트레이터 writer 프롬프트에 자동 주입됨)."""
    rules_path = meta_dir / "dynamic_rules.json"
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else {"rules": []}
    except Exception:
        rules = {"rules": []}
    existing = rules.setdefault("rules", [])
    if rule_text not in existing:
        existing.append(rule_text)
        rules_path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"  [Learn] dynamic_rules.json 추가: {rule_text[:80]}")


def _promote_to_agent_lessons(meta_dir: Path, issue: dict, count: int):
    """agent_lessons.json의 Writer 에이전트에 고우선순위 레슨 등록."""
    lessons_path = meta_dir / "agent_lessons.json"
    try:
        lessons = json.loads(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else {}
    except Exception:
        lessons = {}

    agent_key = "03_Writer_Gardener"
    agent_lessons = lessons.setdefault(agent_key, [])
    # lesson_for_llm 필드 우선 사용 (v8.0 — 더 구체적인 로컬 LLM 교육 레슨)
    llm_lesson  = issue.get("lesson_for_llm", "")
    lesson_text = f"[Claude발견-{count}회반복] {llm_lesson or issue['description'][:120]}"
    existing = next((e for e in agent_lessons if e.get("type") == issue["type"]), None)
    if existing:
        existing["count"] = count
        existing["lesson"] = lesson_text
        existing["last_seen"] = datetime.now().strftime("%Y-%m-%d")
    else:
        agent_lessons.insert(0, {   # 맨 앞에 삽입 (고우선순위)
            "date":      datetime.now().strftime("%Y-%m-%d"),
            "type":      issue["type"],
            "lesson":    lesson_text,
            "score":     0,
            "note":      issue.get("description", "")[:120],
            "count":     count,
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
            "last_seen": datetime.now().strftime("%Y-%m-%d"),
        })
    lessons_path.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"  [Learn] agent_lessons (Writer) 고우선순위 등록: {issue['type']} ({count}회)")


def _update_lesson_lifecycle(meta_dir: Path, found_issue_types: set, title: str):
    """
    Lesson Lifecycle (Decay) 관리.

    PPV 통과한 이슈 타입은 clean_posts += 1
    clean_posts >= 20 → active=false (휴면)
    재발 시 → clean_posts=0, active=true (부활)

    적용 대상: claude_discoveries.json + agent_lessons.json
    """
    DORMANT_THRESHOLD = 20  # 연속 통과 횟수 기준

    # ── claude_discoveries.json ──────────────────────────────────
    discoveries = _load_discoveries(meta_dir)
    resurrected = []
    dormant     = []

    for d in discoveries:
        itype = d.get("type", "")
        if not d.get("promoted_to_rule") and not d.get("promoted_to_agent"):
            continue  # 아직 승격 안 된 건 lifecycle 대상 아님

        if itype in found_issue_types:
            # 재발 → 부활
            was_dormant = not d.get("active", True)
            d["clean_posts"] = 0
            d["active"]      = True
            d["count"]       = d.get("count", 1) + 1
            if was_dormant:
                resurrected.append(itype)
                log.info(f"  [Lifecycle] 🔄 부활: '{itype}' (clean_posts 리셋, count={d['count']})")
        else:
            # 통과 → clean_posts 증가
            d["clean_posts"] = d.get("clean_posts", 0) + 1
            if d["clean_posts"] >= DORMANT_THRESHOLD and d.get("active", True):
                d["active"] = False
                dormant.append(itype)
                log.info(f"  [Lifecycle] 💤 휴면: '{itype}' ({d['clean_posts']}회 연속 미발생)")

    _save_discoveries(meta_dir, discoveries)

    # ── agent_lessons.json ───────────────────────────────────────
    lessons_path = meta_dir / "agent_lessons.json"
    if not lessons_path.exists():
        return
    try:
        lessons = json.loads(lessons_path.read_text(encoding="utf-8"))
        changed = False
        for agent_key, entries in lessons.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                itype = entry.get("type", "")
                if not itype:
                    continue
                if itype in found_issue_types:
                    # 재발 → 부활
                    entry["clean_posts"] = 0
                    entry["active"]      = True
                    changed = True
                else:
                    entry["clean_posts"] = entry.get("clean_posts", 0) + 1
                    if entry["clean_posts"] >= DORMANT_THRESHOLD and entry.get("active", True):
                        entry["active"] = False
                        changed = True
        if changed:
            lessons_path.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"  [Lifecycle] agent_lessons 업데이트 실패: {e}")

    # ── core_lessons.json ────────────────────────────────────────
    core_path = meta_dir / "core_lessons.json"
    if not core_path.exists():
        return
    try:
        core = json.loads(core_path.read_text(encoding="utf-8"))
        changed = False
        for agent_key, entries in core.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                itype = entry.get("type", "") or entry.get("issue", "")
                if not itype:
                    continue
                if itype in found_issue_types:
                    entry["clean_posts"] = 0
                    entry["active"]      = True
                    changed = True
                else:
                    entry["clean_posts"] = entry.get("clean_posts", 0) + 1
                    if entry["clean_posts"] >= DORMANT_THRESHOLD and entry.get("active", True):
                        entry["active"] = False
                        changed = True
        if changed:
            core_path.write_text(json.dumps(core, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"  [Lifecycle] core_lessons 업데이트 실패: {e}")

    if dormant:
        log.info(f"  [Lifecycle] 💤 이번 글 휴면 처리: {dormant}")
    if resurrected:
        log.info(f"  [Lifecycle] 🔄 이번 글 부활: {resurrected}")


def _promote_to_quality_check(issue: dict):
    """5회 이상 반복 버그 → post_quality_check.py AI_PATTERNS에 자동 추가."""
    qc_path = Path(__file__).parent / "post_quality_check.py"
    if not qc_path.exists():
        return
    desc = issue.get("description", "")
    # 패턴으로 쓸 수 있는 짧은 문자열 추출 (핵심 구절)
    pattern_candidate = issue.get("pattern_hint") or re.sub(r'[^\w\s\-]', '', desc).strip().lower()[:40]
    if not pattern_candidate or len(pattern_candidate) < 5:
        return
    try:
        src = qc_path.read_text(encoding="utf-8")
        if pattern_candidate in src:
            return  # 이미 존재
        # AI_PATTERNS 리스트에 추가
        src = src.replace(
            '    "nordic science",\n]',
            f'    "nordic science",\n    "{pattern_candidate}",  # Claude 자동추가 {datetime.now().strftime("%Y-%m-%d")}\n]'
        )
        qc_path.write_text(src, encoding="utf-8")
        log.info(f"  [Learn] post_quality_check.py AI_PATTERNS 자동 추가: {pattern_candidate}")
    except Exception as e:
        log.warning(f"  [Learn] quality_check 패치 실패: {e}")


def _learn_from_scan(issues: list, title: str, meta_dir: Path, post_id: str = ""):
    """
    Claude 스캔 결과를 학습 시스템에 반영.
    발생 횟수에 따라 자동 승격:
      1회: claude_discoveries.json 기록 + hermes_queue.json push (코드 수정 누적 추적)
      2회: dynamic_rules.json 추가 (writer 프롬프트 주입)
      3회: agent_lessons.json 고우선순위 등록
      5회: post_quality_check.py AI_PATTERNS 자동 추가
           + hermes check_tier1_escalation이 자동으로 Qwen3→Claude 코드 수정 트리거
    """
    if not issues or not meta_dir:
        return

    discoveries = _load_discoveries(meta_dir)
    today = datetime.now().strftime("%Y-%m-%d")

    for issue in issues:
        itype = issue.get("type", "unknown")
        desc  = issue.get("description", "")
        sev   = issue.get("severity", "medium")

        # 기존 발견 항목 탐색 (type 기준)
        existing = next((d for d in discoveries if d.get("type") == itype), None)
        if existing:
            existing["count"] += 1
            existing["last_seen"] = today
            if title not in existing.get("titles", []):
                existing.setdefault("titles", []).append(title[:50])
            count = existing["count"]
        else:
            entry = {
                "type":             itype,
                "description":      desc[:120],
                "severity":         sev,
                "fix_instruction":  issue.get("fix_instruction", ""),
                "pattern_hint":     issue.get("pattern_hint", ""),
                "first_seen":       today,
                "last_seen":        today,
                "count":            1,
                "titles":           [title[:50]],
                "promoted_to_rule": False,
            }
            discoveries.append(entry)
            existing = entry
            count = 1

        log.info(f"  [Learn] 발견 기록: {itype} ({count}회, sev={sev})")

        # ── 1회부터: hermes_queue에 push — 5회 누적 시 hernex가 Qwen3→Claude 코드 자동 수정
        _push_hermes_queue(meta_dir, [{
            "cat":       f"html_scan_{itype}",
            "agent":     "post_publish_verifier",
            "label":     f"HTML 스캔 버그: {itype}",
            "score":     0,
            "note":      desc[:120],
            "count":     count,
            "title":     title[:60],
            "post_id":   post_id,
            "queued_at": today,
        }])

        # ── 승격 로직 ────────────────────────────────────────────
        if count >= 2 and not existing.get("promoted_to_rule"):
            rule = f"AVOID: {desc[:100]} (detected {count}x in published posts)"
            _promote_to_dynamic_rules(meta_dir, rule)
            existing["promoted_to_rule"] = True
            existing["rule_text"] = rule

        if count >= 3:
            _promote_to_agent_lessons(meta_dir, existing, count)

        if count >= 5 and sev in ("critical", "high") and not existing.get("promoted_to_qc"):
            _promote_to_quality_check(existing)
            existing["promoted_to_qc"] = True

    _save_discoveries(meta_dir, discoveries)


# ── 좋은 예시 학습 ────────────────────────────────────────────────────────────

def _save_good_example(meta_dir: Path, title: str, total: float, cat_avgs: dict,
                        all_scores: dict, html: str):
    """
    2차 스캔 통과 + 높은 점수 포스팅 → good_examples.json 기록.
    writer 에이전트가 '이렇게 써라'의 기준으로 활용.
    """
    examples_path = meta_dir / "good_examples.json"
    try:
        examples = json.loads(examples_path.read_text(encoding="utf-8")) if examples_path.exists() else []
    except Exception:
        examples = []

    # HTML에서 품질 지표 추출
    text = re.sub(r'<[^>]+>', ' ', html)
    word_count   = len(text.split())
    has_hook     = bool(re.search(r'<(hr|em|blockquote)[^>]*>', html[:3000], re.I))
    has_toc      = 'href="#sec' in html
    has_faq      = bool(re.search(r'<h[23][^>]*>.*?FAQ|Frequently Asked', html, re.I))
    pmid_count   = len(re.findall(r'pubmed\.ncbi\.nlm\.nih\.gov', html))
    img_count    = len(re.findall(r'<img[^>]+>', html, re.I))
    section_count= len(re.findall(r'<h2[^>]*>', html, re.I))

    # 눈에 띄게 잘된 항목 추출 (9점 이상)
    strong_points = [
        f"{cat}({s}/10): {n[:60]}"
        for cat, (s, n) in all_scores.items()
        if s >= 9
    ]

    entry = {
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "title":         title[:80],
        "total":         round(total, 1),
        "cat_avgs":      cat_avgs,
        "strong_points": strong_points,
        "word_count":    word_count,
        "has_hook":      has_hook,
        "has_toc":       has_toc,
        "has_faq":       has_faq,
        "pmid_count":    pmid_count,
        "img_count":     img_count,
        "section_count": section_count,
    }
    examples.append(entry)
    examples = examples[-100:]  # 최근 100건
    examples_path.write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"  [GoodExample] 저장: {title[:50]} ({total}/10) — {len(strong_points)}개 강점")

    # 강점 패턴을 agent_lessons에도 긍정 예시로 기록
    _promote_good_example_to_lessons(meta_dir, entry)


def _promote_good_example_to_lessons(meta_dir: Path, entry: dict):
    """좋은 예시의 강점을 agent_lessons.json에 긍정 가이드로 등록."""
    lessons_path = meta_dir / "agent_lessons.json"
    try:
        lessons = json.loads(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else {}
    except Exception:
        lessons = {}

    agent_key = "03_Writer_Gardener"
    agent_lessons = lessons.setdefault(agent_key, [])
    today = datetime.now().strftime("%Y-%m-%d")

    # 구조 지표 → 긍정 가이드 문장 생성
    guides = []
    if entry["word_count"] >= 2000:
        guides.append(f"✅ 좋은 예시: {entry['word_count']}단어 — 충분한 분량 유지")
    if entry["has_hook"]:
        guides.append("✅ 좋은 예시: 도입부 Hook 존재 — 독자 유입 효과적")
    if entry["has_toc"]:
        guides.append("✅ 좋은 예시: TOC 존재 — 구조 명확")
    if entry["has_faq"]:
        guides.append("✅ 좋은 예시: FAQ 섹션 존재 — 롱테일 SEO 강화")
    if entry["pmid_count"] >= 2:
        guides.append(f"✅ 좋은 예시: PMID {entry['pmid_count']}개 — 과학적 신뢰도 높음")
    if entry["section_count"] >= 5:
        guides.append(f"✅ 좋은 예시: H2 섹션 {entry['section_count']}개 — 적절한 구조")

    for g in guides:
        # 동일 가이드 중복 방지
        if not any(l.get("lesson","") == g for l in agent_lessons):
            agent_lessons.append({
                "date":       today,
                "type":       "good_example",
                "lesson":     g,
                "score":      10,
                "note":       f"출처: {entry['title'][:50]} ({entry['total']}/10)",
                "count":      1,
                "first_seen": today,
                "last_seen":  today,
            })

    try:
        lessons_path.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"  [GoodExample] agent_lessons 긍정 가이드 {len(guides)}개 등록")
    except Exception as e:
        log.warning(f"  [GoodExample] lessons 저장 실패: {e}")


# ── Claude 스마트 스캔 ────────────────────────────────────────────────────────

_SMART_SCAN_PROMPT = """You are a blog post auditor AND teacher for a local LLM. Your job has two parts:
1. Find ALL bugs (technical and semantic)
2. Generate lessons that teach the local LLM to avoid the same mistakes

The post title tells you the supplement topic. Everything in this post should be about that supplement as a DIETARY SUPPLEMENT — nothing else.

=== PART 1: BUG DETECTION ===

Check for ALL of the following:

TECHNICAL BUGS:
1. HTML rendering bugs (entity literals showing as text, broken tags)
2. Duplicate text or sections appearing twice
3. Placeholder text left in ([UPLOAD_...], template variables)
4. "Complete Guide" or "Complete:" remaining in H1 or body text
5. Korean characters in og:description or meta tags
6. DOCTYPE / <html> / <head> accidentally included in post body
7. CSS rendering bugs (# missing from color codes)
8. Broken internal links or missing image src
9. Double consecutive <hr> tags

SEMANTIC BUGS (most important — these are missed by rule-based checks):
10. TOPIC INFILTRATION: Any content that is NOT about the supplement in the title.
    - Example: A selenium supplement post mentioning "automation", "WebDriver", "documentation", "testing framework", "test suite" → CRITICAL bug. The LLM confused selenium (supplement) with Selenium (web automation tool).
    - Check every H2 section, every bullet list, every callout box. If anything doesn't belong in a supplement post, flag it.
11. TIMELINE CONTRADICTION: The post mentions "Week X" as the turning point in two different sections but uses different numbers (e.g., "Week three" in one place and "Week four" in another) → HIGH bug.
12. OVER-IMPROVEMENTS: More than 3 different body systems/symptoms all described as "improved" (energy + mood + sleep + nails + hair + skin + focus + anxiety + headaches all getting better) → HIGH bug. Real people notice 2-3 things max.
13. TITLE vs BODY MISMATCH: Title is experience-style ("I Almost Quit", "What Changed", "The Mistake I Made") but body contains 3+ H2 sections titled "Benefits", "Dosage", "Absorption", "How It Works", "Mechanism" → HIGH bug.
14. SENTENCE-START LOWERCASE: Any <p> tag or content after a quote mark (") that starts with a lowercase letter (that's, maybe, it, etc.) → MEDIUM bug.
15. ARTICLE ERROR: "a instant", "a improvement", "a answer" — vowel-starting words after "a" → MEDIUM bug.
16. AI-PATTERN PHRASES: game-changer, delve into, significant advancement, warzone, consistency is key, in conclusion → MEDIUM bug.

For each issue found, respond in this EXACT JSON format (array):
[
  {
    "type": "short_type_code",
    "severity": "critical|high|medium|low",
    "description": "exact description of the bug",
    "location": "brief location in HTML (e.g. H1, section 3, bullet list)",
    "can_auto_fix": true/false,
    "fix_instruction": "exact fix needed, or null if needs rewrite",
    "lesson_for_llm": "one sentence: what the local LLM must do differently next time to avoid this"
  }
]

If NO bugs found, return: []

POST TITLE: {title}
POST HTML:
{html_preview}"""


def claude_smart_scan(html: str, title: str, ask_ai_fn, meta_dir: Path = None) -> list:
    """
    Claude가 발행된 HTML을 직접 검토해 알려지지 않은 버그까지 탐지.
    반환: 이슈 목록 (dict list)
    """
    if not ask_ai_fn:
        return []

    # 전체 HTML 전달 (앞부분 + 뒷부분 — 중간 생략 방지)
    # Claude 컨텍스트 한계 대비: 앞 12000 + 뒤 6000 (총 18000자 커버)
    if len(html) > 20000:
        html_preview = html[:12000] + "\n\n[...MIDDLE SECTION OMITTED...]\n\n" + html[-6000:]
    else:
        html_preview = html
    prompt = _SMART_SCAN_PROMPT.replace("{title}", title).replace("{html_preview}", html_preview)

    try:
        raw = ask_ai_fn(prompt, "You are a strict HTML/blog post auditor. Respond ONLY with a JSON array.")
        raw = raw.strip()

        # [v7.2] 강화된 JSON 추출 — 3단계 시도
        json_str = None
        # 1) ```json ... ``` 코드블록
        m = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', raw, re.DOTALL)
        if m:
            json_str = m.group(1)
        # 2) 첫 번째 [ 부터 마지막 ] 까지
        if not json_str:
            start = raw.find('[')
            end   = raw.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_str = raw[start:end+1]
        # 3) 빈 배열 응답
        if not json_str:
            return []

        issues = json.loads(json_str)
        if not isinstance(issues, list):
            return []
        log.info(f"  [Claude-Scan] {len(issues)}개 이슈 감지")
        for iss in issues:
            log.info(f"    [{iss.get('severity','?')}] {iss.get('type','?')}: {iss.get('description','')[:80]}")
        return issues
    except Exception as e:
        log.warning(f"  [Claude-Scan] JSON 파싱 실패: {e} | raw 앞 200자: {raw[:200] if 'raw' in dir() else '?'}")
        return []


def apply_claude_scan_fixes(html: str, issues: list) -> tuple[str, list]:
    """
    Claude 스캔 결과 중 can_auto_fix=True인 항목 자동 적용.
    수동 수정 필요 항목은 리스트로 반환.
    """
    import html as _html_lib
    applied = []
    manual  = []

    for iss in issues:
        if not iss.get("can_auto_fix"):
            manual.append(iss)
            continue

        fix = iss.get("fix_instruction", "")
        desc = iss.get("description", "")
        itype = iss.get("type", "")

        try:
            # 공통 패턴 자동 수정
            if "&#8594;" in (fix or desc) or itype in ("arrow_entity", "html_entity"):
                html = html.replace("&#8594;", "→")
                applied.append(f"&#8594;→→ ({desc[:50]})")

            elif "&amp;#" in html and ("double_encoding" in itype or "double" in desc.lower()):
                html = _html_lib.unescape(html)
                applied.append(f"이중인코딩 해제 ({desc[:50]})")

            elif "complete guide" in desc.lower() or itype == "complete_guide_h1":
                html = re.sub(r'Complete Guide:?\s*', '', html, flags=re.I)
                applied.append(f"Complete Guide 제거 ({desc[:50]})")

            elif "placeholder" in itype or "UPLOAD" in (fix or ""):
                # placeholder는 자동 제거보다 레슨 기록이 안전
                manual.append(iss)

            else:
                # fix_instruction에 명시된 내용이 있으면 기록만
                manual.append(iss)

        except Exception as _e:
            log.warning(f"  [Claude-Scan] 자동수정 실패 ({itype}): {_e}")
            manual.append(iss)

    return html, applied, manual  # (수정된 html, 자동수정 목록, 수동필요 목록)


_CLAUDE_REWRITE_PROMPT = """You are fixing a published blog post. Below are the specific bugs found, followed by the full HTML.

BUGS TO FIX:
{bug_list}

RULES:
- Fix ONLY the listed bugs. Do not rewrite other content.
- Keep all existing text, links, images, and structure intact.
- Return ONLY the corrected HTML, no explanation, no markdown fences.

TITLE: {title}
HTML:
{html}"""

def claude_rewrite_fixes(html: str, title: str, issues: list, ask_ai_fn) -> tuple[str, bool]:
    """
    Claude가 직접 내용을 수정해야 하는 버그들(can_auto_fix=False) 처리.
    Returns (fixed_html, was_changed)
    """
    if not ask_ai_fn or not issues:
        return html, False

    # critical/high 만 Claude 재작성 요청 (low는 학습만)
    rewrite_issues = [i for i in issues if i.get("severity") in ("critical", "high")]
    if not rewrite_issues:
        return html, False

    bug_list = "\n".join(
        f"- [{i.get('severity','?').upper()}] {i.get('type','')}: {i.get('description','')} "
        f"(location: {i.get('location','unknown')})"
        for i in rewrite_issues
    )

    prompt = _CLAUDE_REWRITE_PROMPT.format(
        bug_list=bug_list,
        title=title,
        html=html,
    )

    try:
        result = ask_ai_fn(prompt, "You are a precise HTML editor. Return only corrected HTML.")
        result = result.strip()
        # 마크다운 펜스 제거
        if result.startswith("```"):
            result = re.sub(r"^```[a-z]*\n?", "", result)
            result = re.sub(r"\n?```$", "", result)
            result = result.strip()
        if len(result) > 500 and result != html:
            log.info(f"  [Claude-Rewrite] {len(rewrite_issues)}개 버그 수정 완료")
            return result, True
        return html, False
    except Exception as e:
        log.warning(f"  [Claude-Rewrite] 실패: {e}")
        return html, False


def _save_verification_log(meta_dir: Path, entry: dict):
    """포스팅별 검증 전체 기록 — 20_Meta/verification_log.json"""
    log_path = meta_dir / "verification_log.json"
    try:
        records = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    except Exception:
        records = []
    records.append(entry)
    records = records[-200:]  # 최근 200건만 유지
    log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Teacher 전용 Sonnet 호출 ──────────────────────────────────────────────────

def _ask_sonnet(prompt: str, system: str = "") -> str:
    """Claude-Teacher (T1/T2) 전용 — Sonnet 4.6 직접 호출."""
    try:
        import anthropic, os
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            log.warning("  [Teacher-Sonnet] ANTHROPIC_API_KEY 없음 — 스킵")
            return ""
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system or "You are a senior editorial analyst.",
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip() if msg.content else ""
    except Exception as _e:
        log.warning(f"  [Teacher-Sonnet] 호출 실패: {_e}")
        return ""


# ── 외과적 섹션 분리 헬퍼 ────────────────────────────────────────────────────

def _strip_css_js(html: str) -> str:
    """CSS/JS/주석 제거 — Claude에 불필요한 코드 삭제"""
    html = re.sub(r'(?s)<style[^>]*>.*?</style>', '', html)
    html = re.sub(r'(?s)<script[^>]*>.*?</script>', '', html)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    return html


# 카테고리 → 추출 그룹 매핑
_CAT_GROUP = {
    "A1": "HEAD", "A2": "HEAD", "META": "HEAD",
    "B1": "HEAD", "B2": "IMAGES",
    "C1": "BODY", "C2": "BODY", "C3": "BODY",
    "C4": "BODY", "C5": "BODY", "C6": "BODY",
    "D1": "STRUCT", "D2": "STRUCT", "D3": "STRUCT",
    "E1": "STRUCT", "F1": "STRUCT", "F2": "STRUCT",
}


def _extract_surgical_parts(html: str, failing_cats: dict) -> dict:
    """
    실패 카테고리별로 최소 컨텍스트만 추출.
    Returns: {"PART_ID": html_snippet, ...}
    """
    parts = {}
    groups = {_CAT_GROUP.get(c, "BODY") for c in failing_cats}
    stripped = _strip_css_js(html)

    # ── HEAD 그룹 (A, B1, META) ──────────────────────────────────────────────
    if "HEAD" in groups:
        head_m = re.search(r'(?s)<head[^>]*>(.*?)</head>', html)
        if head_m:
            parts["HEAD"] = f"<head>{head_m.group(1)}</head>"

    # ── IMAGES 그룹 (B2) ─────────────────────────────────────────────────────
    if "IMAGES" in groups:
        imgs = re.findall(r'<img[^>]+>', html, re.I)
        if imgs:
            parts["IMAGES"] = "\n".join(imgs[:12])

    # ── BODY 그룹 (C 카테고리) ────────────────────────────────────────────────
    if "BODY" in groups:
        body_m = re.search(r'(?s)<body[^>]*>(.*?)</body>', stripped)
        body   = body_m.group(1) if body_m else stripped

        if "C4" in failing_cats:
            # AI 패턴 문장만 추출 (전체 본문 불필요)
            _AI_KW = ["real talk", "game changer", "bioavailable", "significant advancement",
                      "delve into", "it's worth noting", "consistency is everything",
                      "miracle", "aging slower", "new level", "hamster wheel", "warzone"]
            raw_text = re.sub(r'<[^>]+>', ' ', body)
            sents = re.split(r'(?<=[.!?])\s+', raw_text)
            ai_sents = [s.strip() for s in sents
                        if any(k in s.lower() for k in _AI_KW)][:10]
            parts["C4_SENTENCES"] = "\n".join(ai_sents) if ai_sents else ""

        if "C6" in failing_cats:
            _JARGON = ["chylomicron", "mechanistically", "steady-state", "carboxylation",
                       "osteocalcin", "lymphatic vessel", "plasma half-life", "bioavailability"]
            raw_text = re.sub(r'<[^>]+>', ' ', body)
            sents = re.split(r'(?<=[.!?])\s+', raw_text)
            j_sents = [s.strip() for s in sents
                       if any(j in s.lower() for j in _JARGON)][:8]
            parts["C6_SENTENCES"] = "\n".join(j_sents) if j_sents else ""

        # C1/C2/C3/C5 → H2 섹션 단위로 전송
        body_cats = [c for c in failing_cats if c in ("C1","C2","C3","C5")]
        if body_cats:
            # CSS/JS 제거 후 H2 단위 분리
            secs = re.split(r'(?=<h2[\s>])', body)
            # 각 섹션에 SECTION_N 마커 부여
            for idx, sec in enumerate(secs):
                if sec.strip():
                    parts[f"SECTION_{idx}"] = sec

    # ── STRUCT 그룹 (D, E, F 카테고리) ──────────────────────────────────────
    if "STRUCT" in groups:
        if "D1" in failing_cats:
            ref_m = re.search(r'(?s)(?:PMID|pubmed|references?).*?(?=<h2|</article|</section|$)',
                              stripped, re.I)
            if ref_m:
                parts["D1_REFS"] = ref_m.group(0)[:2000]

        if "D2" in failing_cats:
            lks = re.findall(r'<a[^>]+href="[^"]*nutristacklab[^"]*"[^>]*>[^<]+</a>', html)
            if lks:
                parts["D2_LINKS"] = "\n".join(lks[:10])

        if "D3" in failing_cats:
            disc_m = re.search(
                r'(?s)<div[^>]*(?:disclaimer|takeaway|disclosure)[^>]*>.*?</div>', html, re.I)
            if disc_m:
                parts["D3_BLOCK"] = disc_m.group(0)[:2000]

        if "E1" in failing_cats:
            e1_m = re.search(r'(?s)<div[^>]*medical-disclaimer[^>]*>.*?</div>', html, re.I)
            if e1_m:
                parts["E1_YMYL"] = e1_m.group(0)[:1000]

        if "F1" in failing_cats:
            faq_m = re.search(r'(?s)(<h2[^>]*>.*?FAQ.*?</h2>.*?)(?=<h2|</body|$)', html, re.I)
            if faq_m:
                parts["F1_FAQ"] = faq_m.group(0)[:4000]

        if "F2" in failing_cats:
            rel_m = re.search(r'(?s)<p[^>]*>Related reading:.*?</p>', html, re.I)
            if rel_m:
                parts["F2_RELATED"] = rel_m.group(0)

    # 빈 값 제거
    return {k: v for k, v in parts.items() if v and v.strip()}


def _splice_surgical_response(original_html: str, response: str,
                               extracted: dict) -> tuple[str, list]:
    """
    Claude 응답(마커별 수정본)을 원본 HTML에 splice back.
    Returns (new_html, list_of_applied_part_ids)
    """
    result  = original_html
    applied = []

    for part_id, orig_snippet in extracted.items():
        pattern = rf'\[{re.escape(part_id)}\](.*?)\[/{re.escape(part_id)}\]'
        m = re.search(pattern, response, re.DOTALL)
        if not m:
            continue
        new_snippet = m.group(1).strip()
        if not new_snippet or new_snippet == orig_snippet.strip():
            continue

        # HEAD 교체 — 통째로 replace
        if part_id == "HEAD":
            result = re.sub(r'(?s)<head[^>]*>.*?</head>', new_snippet, result)
            applied.append(part_id)
            continue

        # IMAGES — 각 img 태그 개별 교체
        if part_id == "IMAGES":
            orig_imgs = [l.strip() for l in orig_snippet.splitlines() if l.strip()]
            new_imgs  = [l.strip() for l in new_snippet.splitlines()  if l.strip()]
            for oi, ni in zip(orig_imgs, new_imgs):
                if oi != ni and oi in result:
                    result = result.replace(oi, ni, 1)
            applied.append(part_id)
            continue

        # 문장 레벨 수정 (C4/C6) — 문장 단위 replace
        if part_id in ("C4_SENTENCES", "C6_SENTENCES"):
            orig_sents = [s.strip() for s in orig_snippet.splitlines() if s.strip()]
            new_sents  = [s.strip() for s in new_snippet.splitlines()  if s.strip()]
            changed = False
            for os_, ns_ in zip(orig_sents, new_sents):
                if os_ != ns_ and os_ in result:
                    result = result.replace(os_, ns_, 1)
                    changed = True
            if changed:
                applied.append(part_id)
            continue

        # SECTION / STRUCT — 원본 snippet 위치 찾아서 교체
        orig_clean = orig_snippet.strip()
        if orig_clean and orig_clean in result:
            result = result.replace(orig_clean, new_snippet, 1)
            applied.append(part_id)

    return result, applied


# ── 메인 검증 + 수정 함수 ─────────────────────────────────────────────────────

def verify_and_patch(
    svc,
    blog_id: str,
    post_id: str,
    title: str,
    html: str,
    meta_desc: str,
    ask_ai_fn=None,
    meta_dir: Path = None,
    ask_ai_fn_claude=None,
    topic_type: str = "",
) -> dict:
    """
    발행 직후 품질 검증 + 수술적 수정.

    Returns:
        {
          "passed": bool,
          "grade": str,
          "total": float,
          "cat_avgs": {"A":float, "B":float, ...},
          "items": {
              "A1": {"score":int, "note":str, "action":"pass"|"fixed"|"lesson"|"hermes",
                     "detail":str},  # action 결과 설명
              ...
          },
          "fixed": [...],
          "notified": [...],
          "instant_rejects": [...],
        }
    """
    if not _QC_AVAILABLE:
        log.warning("  [Post-Publish] post_quality_check 임포트 실패 — 검증 스킵")
        return {"passed": True, "grade": "?", "total": 0.0, "items": {}, "cat_avgs": {},
                "fixed": [], "notified": [], "instant_rejects": []}

    if meta_dir is None:
        meta_dir = Path(__file__).parent / "20_Meta"

    links_db = meta_dir / "published_links.json"

    # ── 1. 채점
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

    if total >= 9.0:   grade = "S"
    elif total >= 8.0: grade = "A"
    elif total >= 7.0: grade = "B"
    elif total >= 6.0: grade = "C"
    else:              grade = "F"

    result_cat_avgs = {
        "A": round(a_avg,1), "B": round(b_avg,1), "C": round(c_avg,1),
        "D": round(d_avg,1), "E": round(e_avg,1), "F": round(f_avg,1),
    }

    instant_rejects = check_instant_reject(all_scores, html)

    # 항목별 액션 추적 테이블
    items = {
        cat: {"score": s, "note": n, "action": "pass", "detail": ""}
        for cat, (s, n) in all_scores.items()
    }

    log.info(f"  [Post-Publish] 채점: {total:.1f}/10 ({grade})")

    failing = {cat: (s, n) for cat, (s, n) in all_scores.items() if s < 9}

    # ── Editor 7룰 검사 (채점 직후, 수정 전에 실행) ─────────────────
    _editor_issues = run_editor_checks(html, title, ask_ai_fn, topic_type=topic_type)

    # ── 2. 수술적 수정
    _fn2 = ask_ai_fn_claude or ask_ai_fn   # 재작성·2차 스캔용 (D3 등에서 사용)
    new_html      = html
    current_title = title   # 수정된 제목 추적 (Blogger 패치 시 사용)
    fixed         = []
    notified      = []
    hermes_items  = []

    # ── 반복 버그 우선 자동 수정 (카테고리 무관하게 항상 실행) ──────────
    _d4_html, _d4_fixes = _fix_d4_html_bugs(new_html)
    if _d4_fixes:
        new_html = _d4_html
        for _fx in _d4_fixes:
            fixed.append({"cat": "D4", "label": "HTML 구조 버그", "score": 0,
                           "note": _fx, "detail": f"자동수정: {_fx}"})
            log.info(f"    [D4-auto] {_fx}")

    # ── v8.0: 메타데이터 일관성 체크 + 자동수정 ─────────────────────
    new_html, _meta_ok, _meta_warn = _check_and_fix_metadata(new_html, current_title)
    for _mw in _meta_warn:
        fixed.append({"cat": "META", "label": "메타데이터 불일치", "score": 0,
                      "note": _mw[:120], "detail": _mw[:200]})

    # A1: Complete Guide 제거 + 나쁜 제목 패턴 자동 수정 (Worth Taking / Research Says 등)
    _a1_html, _a1_title = _fix_a1_complete_guide(new_html, title)
    if _a1_title != title:
        new_html      = _a1_html
        current_title = _a1_title
        fixed.append({"cat": "A1", "label": "H1 Complete Guide 제거", "score": 0,
                       "note": f"'{title}' → '{_a1_title}'",
                       "detail": f"H1+제목 수정 완료: {_a1_title[:60]}"})
        log.info(f"    [A1-auto] H1+제목 수정: '{title}' → '{_a1_title[:60]}'")

    # A1 점수 5점 미만이면 추가 제목 수정 (Worth Taking / Research Says 등)
    _a1_score = all_scores.get("A1", (10,))[0]
    if _a1_score < 5:
        _a1b_html, _a1b_title = _fix_a1_bad_title(new_html, current_title, ask_ai_fn=_fn2)
        if _a1b_title != current_title:
            new_html      = _a1b_html
            current_title = _a1b_title
            items["A1"]["action"] = "fixed"
            items["A1"]["detail"] = f"나쁜 제목 수정: '{_a1b_title[:60]}'"
            fixed.append({"cat": "A1", "label": "나쁜 제목 패턴 수정", "score": 0,
                           "note": f"→ '{_a1b_title}'",
                           "detail": items["A1"]["detail"]})

    # AI 구문 자동 치환 (significant advancement, game-changer 등)
    _ai_html, _ai_fixes = _fix_ai_phrases(new_html)
    if _ai_fixes:
        new_html = _ai_html
        for _fx in _ai_fixes:
            fixed.append({"cat": "AI", "label": "AI 구문 치환", "score": 0,
                           "note": _fx, "detail": f"자동치환: {_fx}"})
            log.info(f"    [AI-auto] {_fx}")

    # 오프닝 문단 주제 이탈 자동 수정 (v7.6: 단백질 등 무관 주제로 시작하는 경우)
    _op_html, _op_fixed = _fix_opening_paragraph(new_html, current_title, ask_ai_fn)
    if _op_fixed:
        new_html = _op_html
        fixed.append({"cat": "C0", "label": "오프닝 주제 이탈 수정", "score": 0,
                       "note": "첫 문단이 제목 주제와 무관 → AI 재생성",
                       "detail": "오프닝 교체 완료"})
        log.info("    [C0-auto] 오프닝 주제 이탈 수정 완료")

    # 이미지 alt 오염 자동 수정 (And Complete, slug, topic헤더)
    _alt_html, _alt_fixes = _fix_bad_alts(new_html)
    if _alt_fixes:
        new_html = _alt_html
        for _fx in _alt_fixes:
            fixed.append({"cat": "B2", "label": "alt 오염 수정", "score": 0,
                           "note": _fx, "detail": f"자동수정: {_fx}"})
            log.info(f"    [B2-auto] {_fx}")

    # Related Posts 링크 텍스트 인간화
    _rel_html, _rel_fixes = _fix_related_titles(new_html)
    if _rel_fixes:
        new_html = _rel_html
        for _fx in _rel_fixes:
            fixed.append({"cat": "REL", "label": "Related 제목 인간화", "score": 0,
                           "note": _fx, "detail": f"자동치환: {_fx}"})
            log.info(f"    [REL-auto] {_fx}")

    # og:description 한국어 체크 (자동수정 불가 → 레슨 기록)
    _, _b1_korean_note = _fix_b1_og_desc_korean(new_html)
    if _b1_korean_note and meta_dir:
        _record_lesson(meta_dir, "B1", _b1_korean_note, title, 0)
        notified.append({"cat": "B1", "label": "og:description 한국어", "score": 0, "note": _b1_korean_note})
        log.warning(f"    [B1] {_b1_korean_note}")

    for cat, (score, note) in failing.items():
        label = CATEGORY_LABELS.get(cat, cat)

        # 알림 전용 카테고리 (내용 재작성 필요)
        if cat in _NOTIFY_ONLY:
            count = _record_lesson(meta_dir, cat, note, title, score)
            items[cat]["action"] = "lesson"
            items[cat]["detail"] = f"레슨 #{count} 기록 → 다음 {AGENT_ROUTING.get(cat,'')} 주입"
            notified.append({"cat": cat, "label": label, "score": score, "note": note})
            log.info(f"    [{cat}] 레슨 기록 #{count}")
            continue

        # 즉시 Hermes 큐 (A1/A2/B1 계열)
        if cat in _HERMES_IMMEDIATE:
            hermes_items.append({
                "cat": cat, "agent": AGENT_ROUTING.get(cat, ""),
                "label": label, "score": score, "note": note,
                "count": 1, "title": title[:60], "post_id": post_id,
                "queued_at": datetime.now().strftime("%Y-%m-%d"),
            })
            items[cat]["action"] = "hermes"
            items[cat]["detail"] = "Hermes 큐 등록"

        # ── E1: YMYL 안전 표현 치환
        if cat == "E1":
            new_html, changes = _fix_e1_ymyl(new_html)
            if changes:
                items[cat]["action"] = "fixed"
                items[cat]["detail"] = " / ".join(changes)
                fixed.append({"cat": "E1", "label": label, "score": score,
                               "note": note, "detail": items[cat]["detail"]})
                log.info(f"    [E1] 치환: {changes}")
            else:
                count = _record_lesson(meta_dir, cat, note, title, score)
                items[cat]["action"] = "lesson"
                items[cat]["detail"] = f"치환 대상 없음 — 레슨 #{count}"
                notified.append({"cat": cat, "label": label, "score": score, "note": note})

        # ── B2: 이미지 주입
        elif cat == "B2":
            new_html, img_url = _fix_b2_image(new_html, title)
            if img_url:
                items[cat]["action"] = "fixed"
                items[cat]["detail"] = f"이미지 주입: {img_url[:60]}..."
                fixed.append({"cat": "B2", "label": label, "score": score,
                               "note": note, "detail": items[cat]["detail"]})
                log.info(f"    [B2] 이미지 주입 완료")
            else:
                count = _record_lesson(meta_dir, cat, note, title, score)
                items[cat]["action"] = "lesson"
                items[cat]["detail"] = f"이미지 생성 실패 — 레슨 #{count}"
                notified.append({"cat": cat, "label": label, "score": score, "note": note})

        # ── C1: Hook 주입
        elif cat == "C1":
            new_html, hook_text = _fix_c1_hook(new_html, title, ask_ai_fn)
            if hook_text:
                items[cat]["action"] = "fixed"
                items[cat]["detail"] = f"Hook 주입: {hook_text[:60]}..."
                fixed.append({"cat": "C1", "label": label, "score": score,
                               "note": note, "detail": items[cat]["detail"]})
                log.info(f"    [C1] Hook 주입 완료")
            else:
                count = _record_lesson(meta_dir, cat, note, title, score)
                items[cat]["action"] = "lesson"
                items[cat]["detail"] = f"Hook 생성 실패 — 레슨 #{count}"
                notified.append({"cat": cat, "label": label, "score": score, "note": note})

        # ── D3: 필수요소 (takeaways/disclosure) 주입
        elif cat == "D3":
            new_html, injected = _fix_d3_missing_elements(new_html, title, ask_ai_fn=_fn2 or ask_ai_fn)
            if injected:
                items[cat]["action"] = "fixed"
                items[cat]["detail"] = f"주입 완료: {', '.join(injected)}"
                fixed.append({"cat": "D3", "label": label, "score": score,
                               "note": note, "detail": items[cat]["detail"]})
                log.info(f"    [D3] 요소 주입: {injected}")
            else:
                count = _record_lesson(meta_dir, cat, note, title, score)
                items[cat]["action"] = "lesson"
                items[cat]["detail"] = f"수정 불필요 or 실패 — 레슨 #{count}"
                notified.append({"cat": cat, "label": label, "score": score, "note": note})

        # ── D2: 내부 링크 주입
        elif cat == "D2":
            new_html, injected = _fix_d2_internal_links(new_html, title, links_db)
            if injected:
                items[cat]["action"] = "fixed"
                items[cat]["detail"] = f"링크 {len(injected)}개 주입: {', '.join(t[:30] for t in injected)}"
                fixed.append({"cat": "D2", "label": label, "score": score,
                               "note": note, "detail": items[cat]["detail"]})
                log.info(f"    [D2] 링크 주입: {injected}")
            else:
                count = _record_lesson(meta_dir, cat, note, title, score)
                items[cat]["action"] = "lesson"
                items[cat]["detail"] = f"주입 실패 (관련 포스트 없음) — 레슨 #{count}"
                notified.append({"cat": cat, "label": label, "score": score, "note": note})

        # ── 기타: 레슨 기록만
        else:
            if items[cat]["action"] != "hermes":  # hermes 이미 등록된 경우 덮어쓰지 않음
                count = _record_lesson(meta_dir, cat, note, title, score)
                items[cat]["action"] = "lesson"
                items[cat]["detail"] = f"레슨 #{count} → {AGENT_ROUTING.get(cat, '')} 주입"
                notified.append({"cat": cat, "label": label, "score": score, "note": note})

    # Hermes 큐 저장
    if hermes_items:
        _push_hermes_queue(meta_dir, hermes_items)

    # ── 3. Blogger API 패치 (HTML 수정분 + 제목 수정)
    patch_ok = False
    if fixed and new_html != html and svc and post_id:
        try:
            svc.posts().patch(
                blogId=blog_id, postId=post_id,
                body={"content": new_html, "title": current_title},
            ).execute()
            patch_ok = True
            log.info(f"  [Post-Publish] Blogger HTML 패치 완료 ({len(fixed)}개, 제목='{current_title[:50]}')")
        except Exception as e:
            log.error(f"  [Post-Publish] Blogger 패치 실패: {e}")
            for _f in fixed:
                _f["detail"] += " (패치 실패)"
                items[_f["cat"]]["action"] = "lesson"
                items[_f["cat"]]["detail"] += " → 패치 실패"
            notified.extend(fixed)
            fixed = []

    # ── 4. 라벨 자동 적용 (없을 때만)
    labels_applied = []
    if svc and post_id and blog_id:
        try:
            current = svc.posts().get(
                blogId=blog_id, postId=post_id, fields="labels"
            ).execute()
            if not current.get("labels"):
                gen_labels = _generate_labels(title)
                svc.posts().patch(
                    blogId=blog_id, postId=post_id,
                    body={"labels": gen_labels},
                ).execute()
                labels_applied = gen_labels
                log.info(f"  [Post-Publish] 라벨 {len(gen_labels)}개 자동 적용: {gen_labels}")
            else:
                log.info(f"  [Post-Publish] 라벨 이미 존재 ({len(current['labels'])}개) — 스킵")
        except Exception as e:
            log.warning(f"  [Post-Publish] 라벨 적용 실패: {e}")

    # ── 5. 스마트 스캔 (1차: local 탐지, 2차: Claude API 검증) ─────────────────
    # ask_ai_fn        → 1차 스캔 (local Ollama)
    # ask_ai_fn_claude → 재작성 + 2차 스캔 (Claude API)
    # ask_ai_fn_claude 없으면 ask_ai_fn 하나로 양쪽 처리 (하위 호환)
    # _fn2는 step 2 시작 시점에 이미 정의됨

    claude_auto_fixed  = []
    claude_manual      = []
    claude_rewrote     = False
    scan1_issues       = []
    scan2_issues       = []

    if ask_ai_fn or _fn2:
        try:
            # ── 5-1. 1차 스캔 (local) — 빠른 탐지 + 수정
            log.info("  [Post-Publish] 1차 스캔 시작 (local)...")
            scan1_issues = claude_smart_scan(new_html, title, ask_ai_fn or _fn2, meta_dir)

            if scan1_issues:
                # 단순 패턴 자동 수정 (can_auto_fix=True)
                new_html, claude_auto_fixed, claude_manual = apply_claude_scan_fixes(new_html, scan1_issues)

                # 재작성 (can_auto_fix=False 중 critical/high) — Claude API 우선
                new_html, claude_rewrote = claude_rewrite_fixes(new_html, title, claude_manual, _fn2)
                if claude_rewrote:
                    log.info("  [Post-Publish] 재작성 완료")

                # 학습: 1차 발견 이슈 → Shared Brain + Hermes 큐
                if meta_dir:
                    _learn_from_scan(scan1_issues, title, meta_dir, post_id=post_id)
                    try:
                        import shared_brain as _sb
                        if not _sb.BRAIN_FILE: _sb.init(meta_dir)
                        _sb.record_verifier_scan(scan1_issues, source_agent="post_publish_verifier")
                    except Exception: pass

                # 1차 수정분 Blogger 패치
                if (claude_auto_fixed or claude_rewrote) and svc and post_id:
                    try:
                        svc.posts().patch(
                            blogId=blog_id, postId=post_id,
                            body={"content": new_html, "title": current_title},
                        ).execute()
                        log.info(f"  [Claude-Scan] 1차 수정 패치 완료 (자동={len(claude_auto_fixed)}건, 재작성={claude_rewrote})")
                    except Exception as _pe:
                        log.warning(f"  [Claude-Scan] 1차 패치 실패: {_pe}")
            else:
                log.info("  [Post-Publish] 1차 스캔: 이슈 없음")

            # ── 5-2. 2차 스캔 (Claude API) — 항상 실행, 수정 + 패치까지
            log.info("  [Post-Publish] 2차 스캔 시작 (Claude API)...")
            scan2_issues = claude_smart_scan(new_html, title, _fn2, meta_dir)
            if scan2_issues:
                log.warning(f"  [Post-Publish] 2차 스캔 이슈 {len(scan2_issues)}개:")
                for _m in scan2_issues:
                    log.warning(f"    [{_m.get('severity','?')}] {_m.get('type','')}: {_m.get('description','')[:80]}")

                # 2차 이슈도 자동수정 + Claude 재작성
                new_html, s2_auto, s2_manual = apply_claude_scan_fixes(new_html, scan2_issues)
                new_html, s2_rewrote = claude_rewrite_fixes(new_html, title, s2_manual, _fn2)

                # 2차 수정분 Blogger 패치
                if (s2_auto or s2_rewrote) and svc and post_id:
                    try:
                        svc.posts().patch(
                            blogId=blog_id, postId=post_id,
                            body={"content": new_html, "title": current_title},
                        ).execute()
                        log.info(f"  [2차-스캔] Blogger 패치 완료 (자동={len(s2_auto)}건, 재작성={s2_rewrote})")
                    except Exception as _pe:
                        log.warning(f"  [2차-스캔] 패치 실패: {_pe}")

                # 메모리화 — Tier 3(1-2회)→기록, Tier 2(3-4회)→프롬프트주입, Tier 1(5+회)→코드각인
                if meta_dir:
                    _learn_from_scan(scan2_issues, title, meta_dir, post_id=post_id)
            else:
                log.info("  [Post-Publish] 2차 스캔 통과 — 버그 없음 ✅")
                if meta_dir:
                    _save_good_example(meta_dir, title, total, result_cat_avgs, all_scores, new_html)
                    try:
                        import shared_brain as _sb
                        if not _sb.BRAIN_FILE: _sb.init(meta_dir)
                        _sb.record_post_success(title, all_scores, new_html)
                    except Exception: pass

        except Exception as _se:
            log.warning(f"  [Claude-Scan] 스캔 오류 (무시): {_se}")

    # ── 5-bis. PPV 개선 루프 (9.0 미만이면 Claude 직접 개선, 최대 5회) ──────────
    # [Claude-Teacher] 발동 시점:
    #   (T1) 점수 정체 2회 연속 → 근본 원인 분석
    #   (T2) 5회 소진 후 미달 → AVOID 규칙 추출 → dynamic_rules 자동 추가
    #   (T3) 9점 달성 → 성공 패턴 각인
    # 에러 발동 시점:
    #   (E1) Claude 호출 실패 → 에러 레슨 기록 + 텔레그램
    #   (E2) Blogger 패치 실패 → 에러 레슨 기록 + 텔레그램
    #   (E3) Claude 응답 없음 → 레슨 기록 (텔레그램 없음)
    # ─────────────────────────────────────────────────────────────────────────────

    _PPV_MAX_ROUNDS   = 5
    _ppv_loop_total   = total
    _ppv_loop_html    = new_html
    _ppv_loop_title   = current_title
    _ppv_rounds_done  = 0
    _ppv_prev_total   = total          # 정체 감지용 이전 회차 점수
    _ppv_stagnant_cnt = 0              # 연속 정체 횟수
    # 평균값 초기화 (루프 미진입 시 참조 오류 방지)
    _la_avg = _lb_avg = _lc_avg = _ld_avg = _le_avg = _lf_avg = 0.0
    _l_all: dict = {}

    def _ppv_send_tg(msg: str):
        try:
            import telegram_poster
            telegram_poster.send_alert(msg)
        except Exception:
            pass

    def _ppv_record_error(cat: str, note: str, score: int = 0):
        if meta_dir:
            _record_lesson(meta_dir, cat, note, title, score)
            log.info(f"  [PPV-에러각인] [{cat}] {note[:80]}")

    if _ppv_loop_total < 9.0 and _fn2:
        log.info(
            f"  [PPV-Loop] 시작: 현재 {_ppv_loop_total:.1f}/10 → 목표 9.0 "
            f"(최대 {_PPV_MAX_ROUNDS}회)"
        )
        for _ppv_round in range(1, _PPV_MAX_ROUNDS + 1):

            # 재채점
            _la = score_A(_ppv_loop_title, _ppv_loop_html)
            _lb = score_B(_ppv_loop_html)
            _lc = score_C(_ppv_loop_html, _ppv_loop_title)
            _ld = score_D(_ppv_loop_html)
            _le = score_E(_ppv_loop_html, _ppv_loop_title)
            _lf = score_F(_ppv_loop_html, _ppv_loop_title)
            _l_all = {**_la, **_lb, **_lc, **_ld, **_le, **_lf}

            _la_avg = sum(v[0] for v in _la.values()) / max(len(_la), 1)
            _lb_avg = sum(v[0] for v in _lb.values()) / max(len(_lb), 1)
            _lc_avg = sum(v[0] for v in _lc.values()) / max(len(_lc), 1)
            _ld_avg = sum(v[0] for v in _ld.values()) / max(len(_ld), 1)
            _le_avg = sum(v[0] for v in _le.values()) / max(len(_le), 1)
            _lf_avg = sum(v[0] for v in _lf.values()) / max(len(_lf), 1)
            _ppv_loop_total = (_la_avg + _lb_avg + _lc_avg + _ld_avg + _le_avg + _lf_avg) / 6
            _ppv_rounds_done = _ppv_round

            log.info(f"  [PPV-Loop {_ppv_round}] 재채점: {_ppv_loop_total:.1f}/10")

            # ── (T3) 9점 달성 → 성공 각인 ────────────────────────────────────
            if _ppv_loop_total >= 9.0:
                log.info(f"  [PPV-Loop {_ppv_round}] 목표 달성! {_ppv_loop_total:.1f}/10")
                new_html      = _ppv_loop_html
                current_title = _ppv_loop_title
                log.info(f"  [Claude-Teacher T3] 성공 패턴 각인 시작")
                if meta_dir:
                    try:
                        _save_good_example(
                            meta_dir, title, _ppv_loop_total,
                            {"A": round(_la_avg,1), "B": round(_lb_avg,1),
                             "C": round(_lc_avg,1), "D": round(_ld_avg,1),
                             "E": round(_le_avg,1), "F": round(_lf_avg,1)},
                            _l_all, _ppv_loop_html,
                        )
                        log.info(
                            f"  [Claude-Teacher T3] good_examples 각인: "
                            f"{_ppv_round}회차에서 9점 달성"
                        )
                    except Exception: pass
                    try:
                        import shared_brain as _sb
                        if not _sb.BRAIN_FILE: _sb.init(meta_dir)
                        _sb.record_post_success(title, _l_all, _ppv_loop_html)
                        log.info("  [Claude-Teacher T3] shared_brain DO 패턴 각인 완료")
                    except Exception: pass
                break

            # ── 점수 정체 감지 ────────────────────────────────────────────────
            _improvement = _ppv_loop_total - _ppv_prev_total
            if _improvement < 0.1:
                _ppv_stagnant_cnt += 1
                log.warning(
                    f"  [PPV-Loop {_ppv_round}] 정체 감지: "
                    f"{_ppv_prev_total:.1f} → {_ppv_loop_total:.1f} "
                    f"(개선={_improvement:+.2f}, 연속={_ppv_stagnant_cnt}회)"
                )
            else:
                _ppv_stagnant_cnt = 0
            _ppv_prev_total = _ppv_loop_total

            # ── (T1) 정체 2회 연속 → Claude 근본 원인 분석 ───────────────────
            if _ppv_stagnant_cnt >= 2:
                log.warning(
                    f"  [Claude-Teacher T1] 정체 2회 연속 → 근본 원인 분석 시작"
                )
                _l_failing_stag = {
                    cat: (s, n) for cat, (s, n) in _l_all.items() if s < 9
                }
                _stag_fail_lines = "\n".join(
                    f"  [{cat}] {CATEGORY_LABELS.get(cat, cat)}: {s:.1f}/10 — {n[:100]}"
                    for cat, (s, n) in sorted(_l_failing_stag.items(), key=lambda x: x[1][0])
                )
                _root_prompt = (
                    f"A health supplement blog post has been revised {_ppv_round} times "
                    f"but the score is not improving (stuck at {_ppv_loop_total:.1f}/10).\n\n"
                    f"FAILING ITEMS (not improving):\n{_stag_fail_lines}\n\n"
                    f"FAILING SECTIONS (extracted from the post):\n"
                    f"{_ppv_parts_block if '_ppv_parts_block' in dir() else _stag_fail_lines}\n\n"
                    f"As a senior editor, analyze WHY the score is stuck. "
                    f"Identify the ROOT CAUSE — is it a structural issue, voice issue, "
                    f"content pattern, or something that Claude cannot fix by rewriting alone?\n\n"
                    f"Output format (Korean):\n"
                    f"ROOT_CAUSE: [한 줄 근본 원인]\n"
                    f"WHY_CLAUDE_FAILS: [왜 자동 수정이 안 되는가]\n"
                    f"CODE_FIX_NEEDED: [Writer/Critic 프롬프트에 추가해야 할 규칙]"
                )
                try:
                    log.info("  [Claude-Teacher T1] Sonnet 4.6 호출 중...")
                    _root_analysis = _ask_sonnet(
                        _root_prompt,
                        "You are a senior editorial analyst. Diagnose why automated fixes are failing.",
                    )
                    if _root_analysis and len(_root_analysis) > 50:
                        log.info(
                            f"  [Claude-Teacher T1] 근본 원인 분석 완료:\n"
                            f"{_root_analysis[:400]}"
                        )
                        if meta_dir:
                            _core_path = meta_dir / "core_lessons.json"
                            _core_data = (
                                json.loads(_core_path.read_text(encoding="utf-8"))
                                if _core_path.exists() else {}
                            )
                            if isinstance(_core_data, list):
                                _core_data = {"post_publish_verifier": _core_data}
                            _core_data.setdefault("post_publish_verifier", []).append({
                                "agent":      "post_publish_verifier",
                                "issue":      f"PPV정체({_ppv_round}회): {title[:50]}",
                                "root_cause": _root_analysis[:300],
                                "fix":        "Writer/Critic 프롬프트에 CODE_FIX_NEEDED 항목 추가",
                                "severity":   "high",
                                "count":      3,
                                "first_seen": datetime.now().strftime("%Y-%m-%d"),
                            })
                            _core_path.write_text(
                                json.dumps(_core_data, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            log.info("  [Claude-Teacher T1] core_lessons 각인 완료")
                        _ppv_send_tg(
                            f"[PPV-Teacher T1] 정체 근본 원인 분석\n"
                            f"포스팅: {title[:40]}\n점수: {_ppv_loop_total:.1f}/10\n"
                            f"분석: {_root_analysis[:200]}"
                        )
                except Exception as _ta_e:
                    log.warning(f"  [Claude-Teacher T1] 분석 실패: {_ta_e}")
                break  # 정체 시 루프 중단 (더 시도해도 의미 없음)

            # 실패 항목 수집 (점수 낮은 순)
            _l_failing = {
                cat: (s, n)
                for cat, (s, n) in _l_all.items() if s < 9
            }
            _fail_lines = "\n".join(
                f"  [{cat}] {CATEGORY_LABELS.get(cat, cat)}: {s:.1f}/10 — {n[:120]}"
                for cat, (s, n) in sorted(_l_failing.items(), key=lambda x: x[1][0])
            )
            log.info(
                f"  [PPV-Loop {_ppv_round}] 미달 {len(_l_failing)}개:\n{_fail_lines}"
            )

            # Claude에 개선 요청
            # ── 외과적 섹션 추출 (전체 HTML 대신 실패 부분만) ────────────────
            _ppv_parts = _extract_surgical_parts(_ppv_loop_html, _l_failing)
            _ppv_parts_total = sum(len(v) for v in _ppv_parts.values())
            log.info(
                f"  [PPV-Loop {_ppv_round}] 외과적 추출: "
                f"{len(_ppv_parts)}개 파트, {_ppv_parts_total:,}자 "
                f"(전체 {len(_ppv_loop_html):,}자 대비 "
                f"{100*_ppv_parts_total//max(len(_ppv_loop_html),1)}%)"
            )

            # 파트별 마커 포맷 생성
            _ppv_parts_block = "\n\n".join(
                f"[{pid}]\n{snippet}\n[/{pid}]"
                for pid, snippet in _ppv_parts.items()
            )

            _ppv_prompt = (
                f"Blog post '{_ppv_loop_title}' scored {_ppv_loop_total:.1f}/10 "
                f"(target 9.0+). Round {_ppv_round}/{_PPV_MAX_ROUNDS}.\n\n"
                f"FAILING ITEMS:\n{_fail_lines}\n\n"
                f"SECTIONS TO FIX (only these parts of the HTML):\n"
                f"{_ppv_parts_block}\n\n"
                f"RULES:\n"
                f"- Fix ONLY what's listed in FAILING ITEMS\n"
                f"- Return ONLY the parts you changed, using the SAME markers\n"
                f"- Skip unchanged parts entirely\n"
                f"- Keep all HTML tags, attributes, and structure intact\n"
                f"- Make content feel more human and personal\n"
                f"- No explanation, no markdown fences\n\n"
                f"FORMAT (return only changed parts):\n"
                f"[PART_ID]\n<fixed html>\n[/PART_ID]"
            )
            _ppv_sys = (
                "You are a senior blog editor fixing specific quality issues in a supplement article. "
                "You receive labeled HTML sections. Return ONLY the sections you changed, "
                "using the same [PART_ID]...[/PART_ID] markers. "
                "Do not return unchanged sections. Preserve all HTML structure exactly."
            )

            # ── (E3) Claude 호출 ───────────────────────────────────────────────
            try:
                _ppv_response = _fn2(_ppv_prompt, _ppv_sys)
                if _ppv_response:
                    _ppv_response = _ppv_response.strip()
                    if _ppv_response.startswith("```"):
                        _ppv_response = re.sub(r"^```[a-z]*\n?", "", _ppv_response)
                        _ppv_response = re.sub(r"\n?```$", "", _ppv_response).strip()
            except Exception as _ppv_e:
                # (E1) Claude 호출 실패 → 에러 각인 + 텔레그램
                _ppv_record_error(
                    "PPV_ERR",
                    f"PPV-Loop {_ppv_round}회 Claude 호출 실패: {str(_ppv_e)[:120]}"
                )
                _ppv_send_tg(
                    f"[PPV-에러 E1] Claude 호출 실패\n"
                    f"포스팅: {title[:40]}\n{_ppv_round}회차\n오류: {str(_ppv_e)[:100]}"
                )
                log.warning(f"  [PPV-Loop {_ppv_round}] Claude 호출 실패: {_ppv_e}")
                break

            # (E3) 응답 없음
            if not _ppv_response or len(_ppv_response) < 20:
                _ppv_record_error(
                    "PPV_ERR",
                    f"PPV-Loop {_ppv_round}회 Claude 응답 없음 (len={len(_ppv_response or '')})",
                )
                log.warning(f"  [PPV-Loop {_ppv_round}] Claude 응답 없음 — 루프 종료")
                break

            # ── splice back: 응답을 원본 HTML에 외과적으로 주입 ──────────────
            _ppv_spliced, _applied = _splice_surgical_response(
                _ppv_loop_html, _ppv_response, _ppv_parts
            )
            if not _applied:
                log.info(f"  [PPV-Loop {_ppv_round}] 변경 없음 (splice 매칭 실패) — 루프 종료")
                break
            log.info(f"  [PPV-Loop {_ppv_round}] splice 완료: {_applied}")

            # ── (E2) Blogger 패치 ──────────────────────────────────────────────
            if svc and post_id:
                try:
                    svc.posts().patch(
                        blogId=blog_id, postId=post_id,
                        body={"content": _ppv_spliced, "title": _ppv_loop_title},
                    ).execute()
                    _ppv_loop_html = _ppv_spliced
                    log.info(f"  [PPV-Loop {_ppv_round}] Blogger 패치 완료")
                except Exception as _ppv_pe:
                    _ppv_record_error(
                        "PPV_ERR",
                        f"PPV-Loop {_ppv_round}회 Blogger 패치 실패: {str(_ppv_pe)[:120]}"
                    )
                    _ppv_send_tg(
                        f"[PPV-에러 E2] Blogger 패치 실패\n"
                        f"포스팅: {title[:40]}\n{_ppv_round}회차\n오류: {str(_ppv_pe)[:100]}"
                    )
                    log.warning(f"  [PPV-Loop {_ppv_round}] Blogger 패치 실패: {_ppv_pe}")
                    break
            else:
                _ppv_loop_html = _ppv_spliced

        else:
            # for-else: 5회 소진 후에도 미달
            log.warning(
                f"  [PPV-Loop] {_PPV_MAX_ROUNDS}회 후에도 "
                f"{_ppv_loop_total:.1f}/10"
            )
            if meta_dir and _l_all:
                _l_failing_final = {
                    cat: (s, n) for cat, (s, n) in _l_all.items() if s < 9
                }

                # agent_lessons 기록
                for _fc, (_fs, _fn_note) in _l_failing_final.items():
                    _record_lesson(
                        meta_dir, _fc,
                        f"[PPV-Loop {_PPV_MAX_ROUNDS}회 미달] {_fn_note}",
                        title, _fs,
                    )
                    log.info(f"  [코드각인] [{_fc}] agent_lessons 기록")

                # core_lessons 기록 (count=3 → 즉시 core 승격)
                try:
                    _core_path = meta_dir / "core_lessons.json"
                    _core_data = (
                        json.loads(_core_path.read_text(encoding="utf-8"))
                        if _core_path.exists() else {}
                    )
                    if isinstance(_core_data, list):
                        _core_data = {"post_publish_verifier": _core_data}
                    _core_data.setdefault("post_publish_verifier", []).append({
                        "agent":      "post_publish_verifier",
                        "issue":      f"PPV-Loop {_PPV_MAX_ROUNDS}회 미달: {title[:60]}",
                        "root_cause": (
                            f"최종점수 {_ppv_loop_total:.1f}/10, "
                            f"미달 카테고리: {list(_l_failing_final.keys())}"
                        ),
                        "fix":        "해당 카테고리 패턴을 Writer/Critic 프롬프트에 추가",
                        "severity":   "high",
                        "count":      3,
                        "first_seen": datetime.now().strftime("%Y-%m-%d"),
                    })
                    _core_path.write_text(
                        json.dumps(_core_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    log.info("  [코드각인] core_lessons 기록 완료")
                except Exception as _cl_e:
                    log.warning(f"  [코드각인] core_lessons 기록 실패: {_cl_e}")

                # ── (T2) Claude-Teacher: AVOID 규칙 추출 → dynamic_rules ──────
                log.info("  [Claude-Teacher T2] dynamic_rules AVOID 규칙 추출 시작")
                _stag_fail_summary = "\n".join(
                    f"[{cat}] {CATEGORY_LABELS.get(cat, cat)}: {s:.1f}/10 — {n[:100]}"
                    for cat, (s, n) in sorted(
                        _l_failing_final.items(), key=lambda x: x[1][0]
                    )
                )
                _rule_prompt = (
                    f"A supplement blog post failed quality checks after {_PPV_MAX_ROUNDS} "
                    f"improvement rounds (final score: {_ppv_loop_total:.1f}/10).\n\n"
                    f"PERSISTENT FAILURES:\n{_stag_fail_summary}\n\n"
                    f"FAILING SECTIONS (actual HTML that caused failures):\n"
                    f"{_ppv_parts_block if '_ppv_parts_block' in dir() else _stag_fail_summary}\n\n"
                    f"As a senior editorial analyst, extract 2-4 specific AVOID rules "
                    f"that a Writer agent should follow to prevent these issues in future posts.\n\n"
                    f"Output format (one rule per line, Korean):\n"
                    f"AVOID: [구체적 금지 패턴 — 예시 포함] (detected {_PPV_MAX_ROUNDS}x in PPV-Loop)"
                )
                try:
                    log.info("  [Claude-Teacher T2] Sonnet 4.6 호출 중...")
                    _rule_resp = _ask_sonnet(
                        _rule_prompt,
                        "You are a senior editorial analyst extracting writing rules from failures.",
                    )
                    if _rule_resp:
                        _new_rules = [
                            ln.strip()
                            for ln in _rule_resp.splitlines()
                            if ln.strip().startswith("AVOID:")
                        ]
                        if _new_rules:
                            _dr_path = meta_dir / "dynamic_rules.json"
                            try:
                                _dr = (
                                    json.loads(_dr_path.read_text(encoding="utf-8"))
                                    if _dr_path.exists() else {}
                                )
                            except Exception:
                                _dr = {}
                            _existing = _dr.get("rules", [])
                            _added = [r for r in _new_rules if r not in _existing]
                            _dr["rules"] = (_existing + _added)[-80:]
                            _dr_path.write_text(
                                json.dumps(_dr, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            log.info(
                                f"  [Claude-Teacher T2] dynamic_rules {len(_added)}개 추가: "
                                f"{_added}"
                            )
                            _ppv_send_tg(
                                f"[Claude-Teacher T2] dynamic_rules 자동 각인\n"
                                f"포스팅: {title[:40]}\n"
                                f"추가 규칙 {len(_added)}개:\n" +
                                "\n".join(f"  {r[:80]}" for r in _added)
                            )
                        else:
                            log.info("  [Claude-Teacher T2] 추출된 AVOID 규칙 없음")
                except Exception as _t2_e:
                    log.warning(f"  [Claude-Teacher T2] 규칙 추출 실패: {_t2_e}")

        # 루프 완료: 최종 HTML + 점수 반영
        if _ppv_loop_html != new_html:
            new_html      = _ppv_loop_html
            current_title = _ppv_loop_title

        if _ppv_rounds_done > 0:
            total = _ppv_loop_total
            if total >= 9.0:   grade = "S"
            elif total >= 8.0: grade = "A"
            elif total >= 7.0: grade = "B"
            elif total >= 6.0: grade = "C"
            else:              grade = "F"
            result_cat_avgs = {
                "A": round(_la_avg, 1), "B": round(_lb_avg, 1),
                "C": round(_lc_avg, 1), "D": round(_ld_avg, 1),
                "E": round(_le_avg, 1), "F": round(_lf_avg, 1),
            }
            log.info(
                f"  [PPV-Loop] 완료: {_ppv_rounds_done}회 → "
                f"최종 {total:.1f}/10 ({grade}등급)"
            )

    passed = len(instant_rejects) == 0 and total >= 7.0

    # ── Lesson Lifecycle 업데이트 ──────────────────────────────────────
    # 이번 PPV에서 발견된 이슈 타입 집합 수집
    _all_found_types = set()
    for _s in scan1_issues:
        _all_found_types.add(_s.get("type", ""))
    for _s in scan2_issues:
        _all_found_types.add(_s.get("type", ""))
    _all_found_types.discard("")
    if meta_dir:
        try:
            _update_lesson_lifecycle(meta_dir, _all_found_types, title)
        except Exception as _lc_err:
            log.warning(f"  [Lifecycle] 업데이트 실패 (무시): {_lc_err}")

    # ── ① 못 고친 이슈만 핫 주입 (count=3 즉시 승격) ───────────────────
    # scan2_issues = PPV가 수정 시도했지만 여전히 남은 이슈
    # 이 이슈들은 auto-fix 불가 → Writer가 다음 글에서 직접 회피해야 함
    if scan2_issues and meta_dir:
        try:
            _unfixed_high = [i for i in scan2_issues
                             if i.get("severity") in ("critical", "high")]
            for _iss in _unfixed_high:
                _itype = _iss.get("type", "unknown")
                _desc  = _iss.get("description", "")[:120]
                # claude_discoveries count를 3으로 강제 설정 → 즉시 agent_lessons 승격
                _disc = _load_discoveries(meta_dir)
                _ex = next((d for d in _disc if d.get("type") == _itype), None)
                if _ex:
                    _ex["count"] = max(_ex.get("count", 0), 3)
                    _ex["hot_inject"] = True
                else:
                    _disc.append({
                        "type": _itype, "description": _desc,
                        "severity": _iss.get("severity", "high"),
                        "count": 3, "hot_inject": True,
                        "first_seen": datetime.now().strftime("%Y-%m-%d"),
                        "last_seen":  datetime.now().strftime("%Y-%m-%d"),
                        "titles": [title[:50]],
                        "promoted_to_rule": False,
                    })
                _save_discoveries(meta_dir, _disc)
                _promote_to_agent_lessons(meta_dir, _ex or _disc[-1], 3)
                log.info(f"  [HotInject] 미수정 이슈 즉시 count=3 승격: {_itype}")
        except Exception as _hi_err:
            log.warning(f"  [HotInject] 실패 (무시): {_hi_err}")

    # ── ② 직전 글 피드백 저장 (다음 글 Writer 프롬프트 최상단 주입용) ───
    if meta_dir and scan2_issues:
        try:
            _unfixed_all = [
                {"type": i.get("type",""), "severity": i.get("severity",""),
                 "description": i.get("description","")[:120]}
                for i in scan2_issues
                if i.get("severity") in ("critical","high","medium")
            ]
            if _unfixed_all:
                _last_ppv = {
                    "title":      title[:80],
                    "topic_type": topic_type,
                    "grade":      grade,
                    "total":      round(total, 1),
                    "timestamp":  datetime.now().isoformat(),
                    "unfixed":    _unfixed_all[:5],  # 최대 5개
                }
                (meta_dir / "last_ppv_unfixed.json").write_text(
                    json.dumps(_last_ppv, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                log.info(f"  [LastPPV] 미수정 {len(_unfixed_all)}개 → last_ppv_unfixed.json 저장")
        except Exception as _lp_err:
            log.warning(f"  [LastPPV] 저장 실패 (무시): {_lp_err}")
    elif meta_dir:
        # 이슈 없으면 파일 삭제 (오래된 피드백이 다음 글에 영향 안 주도록)
        try:
            _lpf = meta_dir / "last_ppv_unfixed.json"
            if _lpf.exists():
                _lpf.unlink()
        except Exception:
            pass

    result = {
        "passed":            passed,
        "grade":             grade,
        "total":             round(total, 1),
        "cat_avgs":          result_cat_avgs,
        "items":             items,
        "fixed":             fixed,
        "notified":          notified,
        "instant_rejects":   instant_rejects,
        "patch_ok":          patch_ok,
        "labels_applied":    labels_applied,
        "claude_auto_fixed": claude_auto_fixed,
        "claude_manual":     claude_manual,
        "claude_rewrote":    claude_rewrote,
        "scan1_count":       len(scan1_issues),
        "scan2_count":       len(scan2_issues),
        "scan2_clean":       (len(scan2_issues) == 0),
        "ppv_loop_rounds":   _ppv_rounds_done,
        "editor_issues":     _editor_issues,
    }

    # ── 6. 검증 전체 기록 저장 (verification_log.json)
    if meta_dir:
        try:
            _save_verification_log(meta_dir, {
                "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "post_id":     post_id,
                "title":       title[:80],
                "grade":       grade,
                "total":       round(total, 1),
                "cat_avgs":    result_cat_avgs,
                "passed":      passed,
                "rule_fixed":  [f["cat"] + ":" + f["note"][:50] for f in fixed],
                "scan1_issues": [
                    {"type": i.get("type"), "severity": i.get("severity"), "desc": i.get("description","")[:80]}
                    for i in scan1_issues
                ],
                "claude_auto_fixed": claude_auto_fixed,
                "claude_rewrote":    claude_rewrote,
                "scan2_issues": [
                    {"type": i.get("type"), "severity": i.get("severity"), "desc": i.get("description","")[:80]}
                    for i in scan2_issues
                ],
                "scan2_clean":  result["scan2_clean"],
                "instant_rejects": instant_rejects,
                "lessons":     [n["cat"] + ":" + n["note"][:50] for n in notified],
                "ppv_loop_rounds": _ppv_rounds_done,
                "ppv_loop_final":  round(total, 1),
            })
        except Exception as _le:
            log.warning(f"  [검증로그] 저장 실패: {_le}")

    return result


# ── 디스코드 보고서 생성 ──────────────────────────────────────────────────────

def build_discord_report(title: str, result: dict) -> str:
    """
    항목별 점수 + 문제/조치 내역 디스코드 보고서.
    형식:
      [A] 제목 품질
        A1: 10/10 ✅  OK
        A2:  7/10 ⚠️  57자 (권장 40-65) → 통과
      ...
      ───────────────────
      A:10.0  B:9.0  C:7.2  D:6.5  E:8.0  F:10.0
      종합: 8.1/10  등급: A
      ───────────────────
      수정완료: D2, E1
      레슨기록: C3, D1
    """
    items    = result.get("items", {})
    cat_avgs = result.get("cat_avgs", {})
    total    = result.get("total", 0.0)
    grade    = result.get("grade", "?")
    fixed    = result.get("fixed", [])
    notified = result.get("notified", [])
    rejects  = result.get("instant_rejects", [])

    GROUPS = [
        ("A", "[A] 제목 품질",      ["A1","A2"]),
        ("B", "[B] 메타 데이터",    ["B1","B2"]),
        ("C", "[C] 콘텐츠 품질",    ["C1","C2","C3","C4","C5","C6"]),
        ("D", "[D] 기술적 완성도",  ["D1","D2","D3","D4"]),
        ("E", "[E] 애드센스 가능성",["E1","E2","E3"]),
        ("F", "[F] 정확성",         ["F1", "F2"]),
    ]

    ACTION_ICON = {
        "pass":   "✅",
        "fixed":  "🔧",
        "lesson": "📌",
        "hermes": "🚨",
    }

    lines = [f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
             f"📋 발행 후 품질 검증 리포트",
             f"📝 {title[:55]}",
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━"]

    for grp_key, grp_label, cats in GROUPS:
        avg = cat_avgs.get(grp_key, 0.0)
        lines.append(f"\n{grp_label}  (평균 {avg}/10)")
        for cat in cats:
            if cat not in items:
                continue
            itm    = items[cat]
            score  = itm["score"]
            note   = itm["note"]
            action = itm.get("action", "pass")
            detail = itm.get("detail", "")
            icon   = ACTION_ICON.get(action, "▪️")

            bar = f"{score:2d}/10"
            if action == "pass":
                lines.append(f"  {cat}: {bar} {icon}  {note}")
            elif action == "fixed":
                lines.append(f"  {cat}: {bar} {icon}  문제: {note}")
                lines.append(f"       →  수정: {detail}")
            elif action in ("lesson", "hermes"):
                lines.append(f"  {cat}: {bar} {icon}  문제: {note}")
                lines.append(f"       →  {detail}")

    lines.append(f"\n{'─'*26}")
    avgs_str = "  ".join(f"{k}:{v}" for k, v in cat_avgs.items())
    lines.append(avgs_str)
    lines.append(f"종합: {total}/10  등급: {grade}")
    lines.append(f"{'─'*26}")

    if fixed:
        lines.append(f"🔧 수정완료: {', '.join(f['cat'] for f in fixed)}")
    if notified:
        lines.append(f"📌 레슨기록: {', '.join(n['cat'] for n in notified)}")
    if rejects:
        lines.append(f"🚨 즉각반려: {' | '.join(rejects)}")
    labels_applied = result.get("labels_applied", [])
    if labels_applied:
        lines.append(f"🏷️ 라벨자동적용: {', '.join(labels_applied[:6])}{'…' if len(labels_applied)>6 else ''} ({len(labels_applied)}개)")

    claude_auto = result.get("claude_auto_fixed", [])
    claude_man  = result.get("claude_manual", [])
    if claude_auto:
        lines.append(f"🤖 Claude 자동수정: {' | '.join(str(x)[:40] for x in claude_auto[:3])}")
    if claude_man:
        lines.append(f"🤖 Claude 수동필요: {len(claude_man)}건")
        for m in claude_man[:3]:
            lines.append(f"   [{m.get('severity','?')}] {m.get('description','')[:60]}")

    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
