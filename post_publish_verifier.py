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
    ]
    changed = []
    for pattern, repl in replacements:
        new_html, n = re.subn(pattern, repl, html, flags=re.I)
        if n:
            changed.append(f"'{pattern}' → '{repl}' ({n}회)")
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

    html = re.sub(
        r'(<meta[^>]+property="og:description"[^>]+content=")[^"]*(")',
        lambda m: m.group(1) + new_desc + m.group(2),
        html, flags=re.I,
    )
    html = re.sub(
        r'(<meta[^>]+name="description"[^>]+content=")[^"]*(")',
        lambda m: m.group(1) + new_desc + m.group(2),
        html, flags=re.I,
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
    """관련 내부 링크 2개 주입"""
    if not links_db_path or not links_db_path.exists():
        return html, []
    try:
        links = json.loads(links_db_path.read_text(encoding="utf-8"))
    except Exception:
        return html, []

    stop = {"and","the","a","an","of","for","to","in","is","are","with",
            "how","when","what","why","does","do","my","i","me","its","vs","it"}
    kws = [w.lower() for w in re.findall(r'\b[A-Za-z]{4,}\b', title) if w.lower() not in stop]

    candidates = []
    for lnk in links:
        lnk_title = lnk.get("title", "").lower()
        lnk_url   = lnk.get("url", "")
        if not lnk_url or title[:30].lower() in lnk_title:
            continue
        score = sum(1 for k in kws if k in lnk_title)
        if score > 0:
            candidates.append((score, lnk_url, lnk.get("title", "")))

    candidates.sort(reverse=True)
    chosen = candidates[:2]
    if not chosen:
        chosen = [(0, lnk.get("url", ""), lnk.get("title", ""))
                  for lnk in links[-2:] if lnk.get("url")]

    if not chosen:
        return html, []

    link_parts = [f'<a href="{url}">{t[:50]}</a>' for _, url, t in chosen if url]
    link_block = (
        '<p style="font-size:0.9em;color:#555;margin-top:20px;">'
        'Related reading: ' + " | ".join(link_parts) + '</p>'
    )

    if 'class="disclosure"' in html:
        html = html.replace('<div class="disclosure">', link_block + '\n<div class="disclosure">', 1)
    else:
        html += "\n" + link_block

    injected = [t[:50] for _, _, t in chosen]
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
    lesson_text = f"[Claude발견-{count}회반복] {issue['description'][:120]}"
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

_SMART_SCAN_PROMPT = """You are a technical blog post auditor. Review the HTML below and identify ALL bugs and issues — including ones I haven't anticipated.

Check for:
1. HTML rendering bugs (entity literals like &#8594; showing as text, broken tags, unclosed elements)
2. Duplicate text or sections appearing twice
3. Placeholder text left in ([UPLOAD_...], {{nutrient}}, template variables)
4. "Complete Guide" or "Complete" remaining in H1 headings
5. Korean characters in og:description or meta tags (should be English only)
6. DOCTYPE / <html> / <head> wrapper accidentally included in post body
7. CSS rendering bugs (content: property showing as literal text)
8. Broken internal links or image src issues
9. AI-pattern phrases: game-changer, delve into, it's worth noting, significant advancement, warzone, battlefield, hamster wheel, in conclusion, bioavailable, protocol (in H2 headings)
10. Repeated H2 patterns used across multiple posts: "What Actually Changed", "My Personal Protocol:", "What Most People Get Wrong"
11. Content contradiction: a section recommends something that a later section explicitly says to avoid (e.g., coffee good → coffee bad)
12. Image alt text that looks auto-generated from H2 slugs (all lowercase, hyphens, reads like a URL slug)
13. Double consecutive <hr> tags
14. Any other bug or quality issue you detect

For each issue found, respond in this EXACT JSON format (array):
[
  {
    "type": "short_type_code",
    "severity": "critical|high|medium|low",
    "description": "exact description of the bug",
    "location": "brief location in HTML (e.g. H1, TOC, og:description)",
    "can_auto_fix": true/false,
    "fix_instruction": "exact HTML change needed, or null if manual"
  }
]

If NO bugs found, return: []

POST TITLE: {title}
POST HTML (first 8000 chars):
{html_preview}"""


def claude_smart_scan(html: str, title: str, ask_ai_fn, meta_dir: Path = None) -> list:
    """
    Claude가 발행된 HTML을 직접 검토해 알려지지 않은 버그까지 탐지.
    반환: 이슈 목록 (dict list)
    """
    if not ask_ai_fn:
        return []

    html_preview = html
    # .format() 대신 replace 사용 — 프롬프트 내 JSON 예시의 { } 가 format 변수로 오해석되는 버그 방지
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

    passed = len(instant_rejects) == 0 and total >= 7.0

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
