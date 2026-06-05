"""
NutriStack Lab — Grand Orchestrator v6.0
=========================================
베이스: v4.8 (실제 작동 코드)
v5.0~v5.3: Human Entropy Layer
v5.4: BANNED_PHRASES YMYL 안전 수정
v6.0: 영양소 완전 가이드 모드 추가
  - topic_type "comprehensive_guide" 추가
  - archetype "comprehensive-guide" 추가 (3000-4500단어, 6섹션 고정)
  - COMPREHENSIVE_GUIDE_SECTIONS: 6개 고정 순서 섹션
  - 리서치 프롬프트: 6개 측면(개요/메커니즘/시너지/반감/프로토콜/타임라인) 전체 커버
  - 제목/OG 설명 완전 가이드 전용 템플릿
  - 트리거: 토픽에 "[guide]", "complete guide", "comprehensive guide" 포함 시 자동 감지
"""
import sys, io, os, time, json, re, pickle, random, base64, requests, shutil, logging
# 콘솔 UTF-8 강제 (Windows 워치독 환경에서 한글 깨짐 방지)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import anthropic as _anthropic
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import telegram_poster
import socket
_instance_socket = None
def ensure_single_instance(port):
    global _instance_socket
    try:
        _instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _instance_socket.bind(('127.0.0.1', port))
    except socket.error:
        sys.stdout.write(f"[중복 실행 방지] 이미 실행 중입니다 (포트 {port}). 종료합니다.\n")
        sys.stdout.flush()
        sys.exit(0)

ensure_single_instance(19999)

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('orchestrator.log',encoding='utf-8'), logging.StreamHandler()],
    force=True)

BASE_DIR       = Path(__file__).parent
RAW_DIR        = BASE_DIR / "00_Raw"
TEST_DIR       = BASE_DIR / "00_Test"        # 테스트 전용 (항상 draft, 기록 없음)
COMPLETED_DIR  = BASE_DIR / "01_Completed"
TEST_DONE_DIR  = BASE_DIR / "99_Test_Done"   # 테스트 완료 보관
CHECKPOINT_DIR = BASE_DIR / "02_Checkpoints"
IMAGE_DIR      = BASE_DIR / "05_Images"
PROMPT_DIR     = BASE_DIR / "06_prompts"
LEARN_DIR      = BASE_DIR / "10_Wiki" / "Decisions"
META_DIR       = BASE_DIR / "20_Meta"

for d in [RAW_DIR, TEST_DIR, COMPLETED_DIR, TEST_DONE_DIR, CHECKPOINT_DIR, IMAGE_DIR, LEARN_DIR, META_DIR]:
    d.mkdir(exist_ok=True, parents=True)

SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/webmasters',
]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE          = Path("token.pickle")
BLOG_ID             = "2812259517039331714"
OLLAMA_URL          = "http://localhost:11434/api/generate"


HEAVY_MODEL         = "qwen3:14b-q4_K_M"
LIGHT_MODEL         = "qwen2:7b-instruct-q4_0"
MODEL_RESEARCH      = "gemma4:e4b-it-q8_0"
MODEL_WRITER        = "qwen3:8b-q4_K_M"    # 초안 생성 (로컬 무료)
MODEL_VISUAL_PROMPT = "gemma2:2b"
MODEL_HOOK_CREATIVE = "gemma2:9b"
MODEL_HOOK_TRIM     = "qwen2:7b-instruct-q4_0"
MODEL_TITLE_FAQ     = "qwen3:14b-q4_K_M"
MODEL_LABEL_EXTRACT = "gemma2:2b"
MODEL_LABEL_SEO     = "gemma4:e4b-it-q4_K_M"
MODEL_CRITIC        = "qwen3:14b-q4_K_M"  # 1차 비평 (로컬 무료)
MODEL_MINIMAX_PPV   = "MiniMax-M3"         # MiniMax M3 — PPV 전용
MODEL_MINIMAX_SURGEON = "MiniMax-M2.7"     # 발행 전 부분 수술 전용

MINIMAX_API_URL = "https://api.minimaxi.chat/v1/chat/completions"

SD_API_URL  = "http://127.0.0.1:7860"
SD_ENABLED  = True
SDXL_MODEL  = "epicrealismXL_pureFix.safetensors"
SD15_MODEL  = "epicrealismXL_pureFix.safetensors"

LINKS_DB_FILE        = META_DIR / "published_links.json"
PENDING_APPROVAL     = META_DIR / "pending_approval.json"
LESSONS_FILE         = META_DIR / "agent_lessons.json"
CORE_LESSONS_FILE    = META_DIR / "core_lessons.json"
DYNAMIC_RULES_FILE   = META_DIR / "dynamic_rules.json"
SECTION_PERF_FILE    = META_DIR / "section_performance.json"
GA4_PROPERTY_ID      = "properties/527664358"
BLOG_URL             = "sc-domain:nutristacklab.com"
DISCORD_WEBHOOK_FILE = BASE_DIR / "discord_webhook.json"

# ============================================================
# HUMAN ENTROPY ENGINE
# ============================================================
ARCHETYPES = {
    "science-heavy":      {"weight": 15, "min_words": 2000, "max_words": 4000, "sections": [4,5,6], "faq_prob": 0.7,  "toc_prob": 0.85, "methodology_prob": 1.0,  "kt_prob": 0.95, "science_density": "high"},
    "minimalist":         {"weight": 20, "min_words": 1200, "max_words": 1800, "sections": [3,4],   "faq_prob": 0.3,  "toc_prob": 0.05, "methodology_prob": 1.0,  "kt_prob": 0.5,  "science_density": "none"},
    "quick-answer":       {"weight": 15, "min_words": 1000, "max_words": 1400, "sections": [3],     "faq_prob": 0.4,  "toc_prob": 0.05, "methodology_prob": 1.0,  "kt_prob": 0.6,  "science_density": "low"},
    "journal-tone":       {"weight": 15, "min_words": 1500, "max_words": 2500, "sections": [4,5],   "faq_prob": 0.5,  "toc_prob": 0.1,  "methodology_prob": 1.0,  "kt_prob": 0.5,  "science_density": "medium"},
    "nordic-anecdotal":   {"weight": 15, "min_words": 1400, "max_words": 2200, "sections": [4,5],   "faq_prob": 0.4,  "toc_prob": 0.1,  "methodology_prob": 1.0,  "kt_prob": 0.6,  "science_density": "low"},
    "comparison":         {"weight": 10, "min_words": 1600, "max_words": 2800, "sections": [4,5,6], "faq_prob": 0.6,  "toc_prob": 0.8,  "methodology_prob": 1.0,  "kt_prob": 0.8,  "science_density": "medium"},
    "deep-protocol":      {"weight": 2,  "min_words": 2500, "max_words": 4000, "sections": [5,6],   "faq_prob": 0.99, "toc_prob": 0.9,  "methodology_prob": 1.0,  "kt_prob": 0.99, "science_density": "high"},
    # [v6.0] 영양소 완전 가이드 전용 — 6개 고정 섹션, 항상 TOC/FAQ 포함
    "comprehensive-guide":{"weight": 0,  "min_words": 3000, "max_words": 4500, "sections": [6],     "faq_prob": 1.0,  "toc_prob": 1.0,  "methodology_prob": 1.0,  "kt_prob": 1.0,  "science_density": "high"},
}

# ============================================================
# [v5.6] PATTERN ROTATION ENGINE
# ============================================================
HOOK_PATTERNS = [
    {"id":"FAILED_EXPECTATION","instruction":"Start with: 'I thought [Nutrient] just wasn't working. I'd taken it for a month with zero results.' Describe specific frustration. End with tension. Plain text, 100-140 words.","example_opener":"I thought it just wasn't working."},
    {"id":"DIRECT_REALIZATION","instruction":"Start with: 'It took me three weeks to realize I was taking [Nutrient] exactly the wrong way.' Describe what felt off (energy/focus). End with tension. Plain text, 100-140 words.","example_opener":"It took me three weeks to realize"},
    {"id":"SIMPLE_OBSERVATION","instruction":"Start with a mundane morning routine moment (opening bottle, reading label). Quiet observation leading to doubt. No dramatic weather. End unresolved. Plain text, 100-140 words.","example_opener":"My morning routine felt like it was missing something"},
    {"id":"LABEL_VS_REALITY","instruction":"Start with: 'The label says one thing. My energy levels were saying another.' Describe the disconnect. No drama, just honesty. End with frustration. Plain text, 100-140 words.","example_opener":"The label says one thing."},
    {"id":"SPECIFIC_SYMPTOM","instruction":"Open with ONE physical symptom (brain fog, afternoon crash, stiff joints). Describe exactly where it sits and when it hits. End with doubt. Plain text, 100-140 words.","example_opener":"Brain fog that sits right behind your eyes"},
    {"id":"COUNTER_INTUITIVE","instruction":"Start with something that should have worked but didn't. Create cognitive dissonance. End with unresolved question. Plain text, 100-140 words.","example_opener":"Everything checked out on paper."},
    {"id":"CONVERSATION_OVERHEARD","instruction":"Start with a brief real exchange (doctor/friend/podcast). A small detail that reframed your routine. End with the question it raised. Plain text, 100-140 words.","example_opener":"My doctor mentioned it almost as an aside."},
    {"id":"TIMING_EXPERIMENT","instruction":"Open with a specific self-experiment (changing time/dose/combo). Describe what shifted without giving resolution. End before conclusion. Plain text, 100-140 words.","example_opener":"I switched the timing and something shifted."},
    {"id":"NUMBER_ANCHOR","instruction":"Open with a specific number (6 weeks, 2000mg, 3rd bottle). Let the number signal specificity. End with what it made you question. Plain text, 100-140 words.","example_opener":"Six weeks. Same dose. Still nothing."},
    {"id":"QUIET_MOMENT","instruction":"Open with a quiet mundane moment in an ordinary room (kitchen counter, phone screen). No weather. Small honest moment triggering doubt. End with tension. Plain text, 100-140 words.","example_opener":"The hum of the refrigerator in a quiet kitchen"},
]

TITLE_STYLE_INSTRUCTIONS = [
    "Write a title: 'Why [Nutrient] Didn't Work Until I Took It With Breakfast' — raw, honest.",
    "Write a title: 'Taking [Nutrient] on an Empty Stomach Did Nothing for Me' — experience-first.",
    "Write a title: 'What Actually Changed When I Took [Nutrient] With Food' — personal result.",
    "Write a title: 'I Tested [Nutrient] for 3 Weeks: Here is the Honest Truth' — investigative.",
    "Write a title: 'Why I Stopped Taking [Nutrient] Alone (And What I Do Now)' — story-driven.",
    "Write a title: 'The Specific Timing That Finally Made [Nutrient] Work' — practical.",
    "Write a title: 'Does [Nutrient] Actually Help With Screen Fatigue? My Experience' — question.",
    "Write a title: 'My Morning [Nutrient] Routine: No Hype, Just Results' — routine focus.",
]


OG_DESC_TEMPLATES = [
    "What I learned after adjusting my {kw} routine. No overnight results, but subtle changes that mattered.",
    "I took {kw} for weeks with mixed results. Here's the timing and dosage approach that finally made a difference.",
    "The research on {kw} is often different from real-world results. Here is my personal experience testing it.",
    "What actually changed when I focused on {kw} timing. A practical look at the results and the consistency required.",
    "If {kw} isn't working for you, it might be the context. My notes on what I adjusted to see progress.",
]

OG_DESC_TEMPLATES_DUAL = [
    "Does {kw} actually work better together? Here's what changed after I tested this combination for weeks.",
    "Combining {kw} was a learning process. Here's the routine that worked for me and what to watch out for.",
    "The science behind {kw} synergy is one thing; real experience is another. My notes on testing them.",
]

CAPTION_TEMPLATES = [
    "What {section} actually felt like — week 4 in.",
    "My experience with {section}: nothing dramatic.",
    "Honest notes on {section}.",
    "{section}: slower to kick in than I expected.",
    "What changed after I stopped ignoring {section}.",
    "Real talk on {section} — no hype.",
    "This is what {section} looked like in practice.",
    "Still figuring out {section}, honestly.",
    "{section} — not what the label says.",
    "My setup during {section} testing.",
]

# ── [v7.0] 패턴 다양화 상수 ──────────────────────────────────

# Key Takeaways 박스 제목 변형 (5가지)
KT_TITLES = [
    "Before You Read On",
    "What surprised me:",
    "What I Found",
    "The honest version:",
    "Three things I wish I'd known:",
]

# TOC 스타일 변형 (접두사 + 스타일)
TOC_STYLES = [
    {"prefix": "→ ", "bg": "#f9f9f9", "border": "#ddd", "link_color": "#2980b9"},
    {"prefix": "",   "bg": "#f5f5f5", "border": "#ccc", "link_color": "#0066cc"},
    {"prefix": "· ", "bg": "#fafafa", "border": "#e0e0e0", "link_color": "#333"},
    {"prefix": "",   "bg": "#fff8f0", "border": "#d4a574", "link_color": "#8b5e3c"},
]

# KT 박스 색상 변형 (배경, 좌측 보더)
KT_THEMES = [
    ("#f0f7ff", "#2a6496"),
    ("#f0fff4", "#27ae60"),
    ("#fff8f0", "#e67e22"),
    ("#f9f0ff", "#8e44ad"),
    ("#f0f4ff", "#2c3e50"),
]

# URL 시드 템플릿 (Blogger URL 슬러그 인간화용)
URL_SEED_TEMPLATES = [
    "why-{nutrient}-finally-worked-for-me",
    "testing-{nutrient}-for-six-weeks",
    "my-{nutrient}-routine-and-what-changed",
    "what-{nutrient}-actually-did-for-my-energy",
    "the-{nutrient}-mistake-i-kept-making",
    "how-i-take-{nutrient}-now",
    "what-i-learned-from-{nutrient}",
    "six-weeks-on-{nutrient}-honest-results",
    "the-{nutrient}-timing-that-changed-things",
    "my-honest-notes-on-{nutrient}",
]

def generate_url_seed(nutrient_label: str) -> str:
    """포스트 최초 발행 시 인간적인 URL 슬러그 생성용 짧은 제목."""
    slug = re.sub(r'[^\w\s]', '', nutrient_label).strip().lower().replace(' ', '-')
    template = random.choice(URL_SEED_TEMPLATES)
    return template.format(nutrient=slug)

def get_next_pattern(patterns, last_file_name, key_id="id", avoid_last_n=3):
    """패턴 랜덤 선택 — 최근 avoid_last_n개 사용 이력을 피해 반복 방지."""
    last_file = META_DIR / last_file_name
    history = []
    if last_file.exists():
        try:
            data = json.loads(last_file.read_text(encoding='utf-8'))
            history = data.get("history", [data.get("last")] if data.get("last") else [])
        except: pass

    recent = set(history[-avoid_last_n:])

    if isinstance(patterns[0], dict):
        available = [p for p in patterns if p[key_id] not in recent]
        if not available:
            available = patterns  # 전체 순환 시 리셋
        chosen  = random.choice(available)
        new_val = chosen[key_id]
    else:
        available = [p for p in patterns if p not in recent]
        if not available:
            available = patterns
        chosen  = random.choice(available)
        new_val = chosen

    history.append(new_val)
    last_file.write_text(
        json.dumps({"last": new_val, "history": history[-10:]}, ensure_ascii=False),
        encoding='utf-8'
    )
    return chosen

def generate_og_description(topic, title):
    # [v5.9.9.9] 'Common', 'Mistakes' 등 오염 단어 제거 및 영양소 중심 키워드 추출
    black_list = {"common", "mistakes", "tips", "avoid", "timing", "guide", "protocol", "best", "how", "why"}
    topic_clean = re.sub(r'[^\w\s]', ' ', topic).lower()
    keywords = [w for w in topic_clean.split() if len(w) > 3 and w not in black_list]
    
    # 영양소 DB에서 다시 한번 확인
    nutrients = extract_nutrients_from_topic(topic)
    if nutrients:
        # synergy(and/with) 토픽만 2개 연결, 단일 토픽은 1개만 (Vitamin And Cobalamin 오염 방지)
        is_synergy = ' and ' in topic.lower() or ' with ' in topic.lower()
        kw = ' and '.join(nutrients[:2]) if is_synergy and len(nutrients) >= 2 else nutrients[0]
    else:
        kw = ' and '.join(keywords[:2]) if len(keywords) >= 2 else (keywords[0] if keywords else topic[:15])
    
    kw = kw.title() # 첫 글자 대문자
    
    # [v6.0] 완전 가이드 / 조합 / 단일 영양소 템플릿 분리
    _topic_type_ctx = topic.lower()
    if any(x in _topic_type_ctx for x in ["[guide]", "complete guide", "comprehensive guide", "ultimate guide"]):
        desc = random.choice(OG_DESC_TEMPLATES_GUIDE).format(kw=kw)
    elif ' and ' in kw.lower() or ' with ' in kw.lower():
        desc = random.choice(OG_DESC_TEMPLATES_DUAL).format(kw=kw)
    else:
        desc = random.choice(OG_DESC_TEMPLATES).format(kw=kw)
        
    if len(desc) > 155: desc = desc[:152] + "..."
    return desc

def random_caption(section_label, topic):
    template = random.choice(CAPTION_TEMPLATES)
    return template.format(section=section_label, topic=topic[:45])

def _sync_all_meta(html: str, title: str, desc: str) -> str:
    """
    v8.1 단일 소스 메타데이터 동기화
    title → H1 + og:title + JSON-LD headline (3곳)
    desc  → og:description + JSON-LD description + JS var desc (3곳)
    모두 같은 변수에서 주입 → H1≠OG≠JSON-LD 불일치 원천 차단
    """
    if not title or not desc:
        return html

    # ── 제목 3곳 ────────────────────────────────────────────────
    # H1
    html = re.sub(
        r'(<h1[^>]*>)[^<]*(</h1>)',
        lambda m: m.group(1) + title + m.group(2),
        html, flags=re.I
    )
    # og:title (양쪽 속성 순서 처리)
    html = re.sub(
        r'(property=["\']og:title["\'][^>]*content=")[^"]+(")',
        lambda m: m.group(1) + title + m.group(2), html, flags=re.I
    )
    html = re.sub(
        r'(content=")[^"]+("[^>]*property=["\']og:title["\'])',
        lambda m: m.group(1) + title + m.group(2), html, flags=re.I
    )
    # JSON-LD headline
    html = re.sub(
        r'("headline"\s*:\s*")[^"]+(")',
        lambda m: m.group(1) + title + m.group(2), html
    )

    # ── 설명 3곳 ────────────────────────────────────────────────
    import html as _htmllib
    desc_esc = _htmllib.escape(desc, quote=True)  # apostrophe → &#x27;

    # og:description — 태그 전체 교체 (content 속성 내 apostrophe 오작동 방지)
    _new_og_desc = f'<meta property="og:description" content="{desc_esc}"/>'
    html = re.sub(
        r'<meta[^>]*property=["\']og:description["\'][^/]*/?>',
        _new_og_desc, html, flags=re.I
    )
    html = re.sub(
        r'<meta[^>]*content=["\'][^"\']*["\'][^>]*property=["\']og:description["\'][^/]*/?>',
        _new_og_desc, html, flags=re.I
    )

    # JSON-LD description (JSON 내부라 HTML 이스케이프 불필요, Python repr 문자만 주의)
    _desc_json = desc.replace('"', '\\"')
    html = re.sub(
        r'("description"\s*:\s*")[^"]+(")',
        lambda m: m.group(1) + _desc_json + m.group(2), html
    )
    # JS var desc — 세미콜론 기준 전체 교체
    html = re.sub(
        r'var\s+desc\s*=\s*"[^;]+";',
        f'var desc = "{_desc_json}";',
        html
    )

    logging.info(f"  🔗 [MetaSync] 제목 3곳 + 설명 3곳 → 단일 소스 동기화 완료")
    return html


def inject_meta_description(html, description):
    desc_escaped = description.replace('"', '\\"')
    today_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # [v6.0] 강화된 BlogPosting JSON-LD 스키마 (canonical url은 발행 후 patch_seo_tags에서 주입)
    meta_block = (
        f'<script type="application/ld+json">'
        f'{{'
        f'"@context":"https://schema.org",'
        f'"@type":"BlogPosting",'
        f'"description":"{desc_escaped}",'
        f'"author":{{"@type":"Person","name":"Erik Lindström"}},'
        f'"publisher":{{"@type":"Organization","name":"NutriStack Lab",'
        f'"logo":{{"@type":"ImageObject","url":"https://www.nutristacklab.com/favicon.ico"}}}},'
        f'"datePublished":"{today_str}",'
        f'"inLanguage":"en-US"'
        f'}}'
        f'</script>\n'
    )
    # [v6.0] JS: canonical + og:url + description 동시 주입
    js_injector = (
        f'<script type="text/javascript">\n'
        f'document.addEventListener("DOMContentLoaded", function() {{\n'
        f'  var desc = "{desc_escaped}";\n'
        f'  var pageUrl = window.location.href.split("?")[0];\n'
        f'  var tags = [\n'
        f'    {{ name: "description",       attr: "name",     value: desc }},\n'
        f'    {{ name: "og:description",    attr: "property", value: desc }},\n'
        f'    {{ name: "twitter:description",attr: "name",    value: desc }},\n'
        f'    {{ name: "og:url",            attr: "property", value: pageUrl }},\n'
        f'    {{ name: "og:type",           attr: "property", value: "article" }}\n'
        f'  ];\n'
        f'  tags.forEach(function(t) {{\n'
        f'    var el = document.querySelector("meta[" + t.attr + "=\'" + t.name + "\']");\n'
        f'    if (el) {{ el.setAttribute("content", t.value); }}\n'
        f'    else {{\n'
        f'      var meta = document.createElement("meta");\n'
        f'      meta.setAttribute(t.attr, t.name);\n'
        f'      meta.setAttribute("content", t.value);\n'
        f'      document.head.appendChild(meta);\n'
        f'    }}\n'
        f'  }});\n'
        f'  // canonical 동적 주입 (head에 없을 경우)\n'
        f'  if (!document.querySelector("link[rel=\'canonical\']")) {{\n'
        f'    var link = document.createElement("link");\n'
        f'    link.rel = "canonical"; link.href = pageUrl;\n'
        f'    document.head.appendChild(link);\n'
        f'  }}\n'
        f'}});\n'
        f'</script>\n'
    )
    return meta_block + js_injector + html


def patch_seo_tags(html: str, url: str, title: str, description: str, image_url: str = "") -> str:
    """발행 후 확정된 URL로 canonical + og:url + JSON-LD url 필드를 HTML에 주입."""
    if not url or not url.startswith("http"):
        return html
    url_escaped  = url.replace('"', '\\"')
    desc_escaped = description.replace('"', '\\"')
    title_esc    = title.replace('"', '\\"')
    today_str    = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # og:image — 히어로 이미지 URL (Pinterest/SNS 공유 시 핵심)
    _img_tag = ""
    _img_jsonld = ""
    if image_url and image_url.startswith("http") and "UPLOAD_TO" not in image_url:
        _img_tag = f'<meta property="og:image" content="{image_url}"/>\n'
        _img_jsonld = f'"image":"{image_url}",'

    patch = (
        # 표준 HTML canonical (body 내 — Blogger가 head로 올리지 않지만 크롤러가 감지할 수 있음)
        f'<link rel="canonical" href="{url_escaped}"/>\n'
        # Open Graph 필수 태그
        f'<meta property="og:title" content="{title_esc}"/>\n'
        f'<meta property="og:description" content="{desc_escaped}"/>\n'
        f'<meta property="og:url" content="{url_escaped}"/>\n'
        f'<meta property="og:type" content="article"/>\n'
        + _img_tag +
        # 완전한 BlogPosting JSON-LD (url + mainEntityOfPage 포함)
        f'<script type="application/ld+json">'
        f'{{'
        f'"@context":"https://schema.org",'
        f'"@type":"BlogPosting",'
        f'"mainEntityOfPage":{{"@type":"WebPage","@id":"{url_escaped}"}},'
        f'"headline":"{title_esc}",'
        f'"description":"{desc_escaped}",'
        f'{_img_jsonld}'
        f'"url":"{url_escaped}",'
        f'"datePublished":"{today_str}",'
        f'"author":{{"@type":"Person","name":"Erik Lindström"}},'
        f'"publisher":{{"@type":"Organization","name":"NutriStack Lab",'
        f'"logo":{{"@type":"ImageObject","url":"https://www.nutristacklab.com/favicon.ico"}}}}'
        f'}}'
        f'</script>\n'
    )
    # 기존 단순 JSON-LD 블록 교체 (있으면) — 없으면 앞에 추가
    old_schema_pat = r'<script type="application/ld\+json">.*?</script>\n?'
    if re.search(old_schema_pat, html, re.DOTALL):
        html = re.sub(old_schema_pat, '', html, count=1, flags=re.DOTALL)
    return patch + html


def pick_archetype():
    """아키타입 가중치 랜덤 선택 — 최근 3개 사용 이력 제외로 반복 방지."""
    arch_hist_file = META_DIR / "last_archetype.json"
    history = []
    if arch_hist_file.exists():
        try:
            data    = json.loads(arch_hist_file.read_text(encoding='utf-8'))
            history = data.get("history", [data.get("last")] if data.get("last") else [])
        except: pass

    recent  = set(history[-3:])
    names   = list(ARCHETYPES.keys())
    weights = [ARCHETYPES[n]["weight"] if n not in recent else 0 for n in names]
    if sum(weights) == 0:
        weights = [ARCHETYPES[n]["weight"] for n in names]  # 전체 순환 시 리셋

    chosen = random.choices(names, weights=weights, k=1)[0]
    history.append(chosen)
    arch_hist_file.write_text(
        json.dumps({"last": chosen, "history": history[-10:]}, ensure_ascii=False),
        encoding='utf-8'
    )
    return chosen

def get_archetype_config(name, topic_type="synergy"):

    cfg = ARCHETYPES[name]
    cfg = ARCHETYPES[name].copy()
    
    # [v5.4] 주제별 가중치 보정
    boost = 1.0
    if topic_type in ["food-combo", "protocol", "synergy", "antagonism", "deficiency"]:
        boost = 1.3
        
    # [v5.9.9.7] Chaos Factor - 구조 반복 파괴를 위한 랜덤성 주입
    # comprehensive-guide는 항상 TOC/FAQ 고정이므로 제외
    if name != "comprehensive-guide":
        if random.random() < 0.3: cfg["faq_prob"] = 0
        if random.random() < 0.2: cfg["toc_prob"] = 0
    cfg["include_table"] = random.random() > 0.4 # 40% 확률로 표 제외 지시용
    
    return {
        "name":               name,
        "target_words":       random.randint(cfg["min_words"], cfg["max_words"]),
        "section_count":      random.choice(cfg["sections"]),
        "include_faq":        random.random() < min(1.0, cfg["faq_prob"] * boost),
        "include_toc":        random.random() < cfg.get("toc_prob", 0.5),
        "include_methodology":True,  # 항상 포함 — 브랜드 일관성
        "include_kt":         random.random() < min(1.0, cfg["kt_prob"] * boost),
        "include_cliff":      random.random() < 0.4,
        "include_nordic":     random.random() < 0.4,
        "include_table":      cfg.get("include_table", True),
        "image_count":        random.choices([0,1,2,3,4,5], weights=[15,20,25,20,15,5], k=1)[0],
    }

# [v6.0] 완전 가이드 고정 섹션 (순서 변경 금지)
# ── 가이드 구조 템플릿 6종 ────────────────────────────────────────────────────
# 매 포스팅마다 템플릿 하나를 랜덤 선택 → 131개 전체에서 완전히 다른 읽기 경험
# 시너지/반감은 가이드 131개 완료 후 별도 포스트 타입으로 사용
COMPREHENSIVE_GUIDE_TEMPLATES = {

    "A_mechanism_first": {
        "label": "Mechanism-First",
        "tone": "science-backed personal experience: explain how it works, then show what that meant in practice",
        "sections": [
            "Why It Works the Way It Does",
            "The Form I Settled On (And Why)",
            "Dose and Timing: What I Landed On",
            "The First Month: Honest Notes",
            "What's Still True Six Months Later",
            "Who This Actually Makes Sense For",
        ],
    },

    "B_success_story": {
        "label": "Success Story",
        "tone": "positive narrative arc: start with doubt, end with why you're still taking it",
        "sections": [
            "Why I Almost Didn't Try It",
            "The Turning Point: What Changed in Week Four",
            "What I Was Doing That Helped",
            "What Changed in My Body (and What Didn't)",
            "Why I'm Still Taking It",
            "What I'd Tell Someone Starting Out",
        ],
    },

    "C_failure_to_fix": {
        "label": "Failure-to-Fix",
        "tone": "honest struggle narrative: what went wrong first, what the fix was, and the real outcome",
        "sections": [
            "What Went Wrong the First Time",
            "Why I Gave It Another Chance",
            "The Adjustment That Changed Everything",
            "What I Had to Stop Doing",
            "Where Things Stand Now",
            "The Honest Caveat I Don't See Mentioned Enough",
        ],
    },

    "D_three_mistakes": {
        "label": "Three Mistakes",
        "tone": "structured lesson format: three specific mistakes, then what actually works",
        "sections": [
            "The First Thing I Got Wrong",
            "The Second Mistake (This One Took Longer to Figure Out)",
            "The Third Mistake I Keep Seeing Others Make",
            "What I Do Differently Now",
            "The Results After Getting It Right",
            "Is It Actually Worth It?",
        ],
    },

    "E_period_based": {
        "label": "Period-Based Timeline",
        "tone": "chronological diary of adaptation: show the arc from uncertainty to clarity over months",
        "sections": [
            "Weeks 1–2: What I Expected vs. Reality",
            "Month One: Where Things Started to Shift",
            "Month Two: The Patterns I Started Noticing",
            "What I Adjusted Along the Way",
            "Where Things Stand at Month Three",
            "What I'd Do Differently From Day One",
        ],
    },

    "F_journal": {
        "label": "Journal Format",
        "tone": "intimate first-person log: specific dated observations, raw and unpolished",
        "sections": [
            "Day 1: First Impressions",
            "Week 2: The Dip I Didn't Expect",
            "Week 6: Something Actually Shifted",
            "Month 2: Settling Into a Routine",
            "What I'm Still Figuring Out",
            "The Honest Summary (No Hype)",
        ],
    },
}

# 목표 비율 — 131개 전체에 걸쳐 이 비율로 수렴
# C: 30개, B: 25개, E: 20개, D: 15개, F: 5개, A: 5개 (100개 기준)
GUIDE_TEMPLATE_RATIOS = {
    "C_failure_to_fix":   0.30,   # 가장 자연스럽고 검색 잘 먹힘 (30개)
    "B_success_story":    0.25,   # 긍정 내러티브, 계속 유지 (25개)
    "E_period_based":     0.20,   # "6주 후", "30일 후" 패턴 (20개)
    "D_three_mistakes":   0.15,   # 롱테일 검색 (15개)
    "F_journal":          0.05,   # 인간성 강화, 희소성 유지 (5개)
    "A_mechanism_first":  0.05,   # AI footprint 최소화 (5개)
}

# 하위 호환용
COMPREHENSIVE_GUIDE_SECTION_POOLS = [
    [t["sections"][i] for t in COMPREHENSIVE_GUIDE_TEMPLATES.values()]
    for i in range(6)
]
COMPREHENSIVE_GUIDE_SECTIONS = list(COMPREHENSIVE_GUIDE_TEMPLATES["A_mechanism_first"]["sections"])

OG_DESC_TEMPLATES_GUIDE = [
    "What I actually experienced on {kw} — the mechanism, my honest timeline, and what I'd do differently.",
    "Six months on {kw}: what worked, what didn't, and the part no one talks about.",
    "My {kw} experiment: from skeptic to consistent user — dose, timing, and real results.",
    "Testing {kw} for months. Here's the honest version of what happened.",
]

TITLE_STYLES_GUIDE = [
    # SEO 키워드(영양소+측면) + 개인 경험 훅 형태
    # 주의: "Benefits, Dosage, and Side Effects" 3종 세트 절대 금지 (v7.9)
    "{nutrient} Dosage: The Mistake That Delayed My Results",
    "{nutrient} Timing: The One Change That Made the Difference",
    "{nutrient} Absorption: Why I Got It Wrong for Months",
    "{nutrient} Deficiency: How I Finally Fixed My Energy Levels",
    "{nutrient} Results: The Honest Version After Six Weeks",
    "Why {nutrient} Felt Useless Until I Changed the Timing",
    "The {nutrient} Mistake I Kept Making for Months",
    "I Almost Quit {nutrient} After Two Weeks",
    "What Changed After Six Weeks on {nutrient}",
    "Why {nutrient} Felt Useless Until Week Four",
]

SECTION_POOLS = {
    "synergy": [
        "What Actually Worked Better for Me",
        "The Timing Experiment: My Morning vs Night Results",
        "The Simple Choice I Finally Made",
        "How it Actually Felt During the First Week",
        "Why I Started Combining These Two",
        "The Week I Almost Stopped and What Kept Me Going",
        "Who Gets the Most Out of This Combination",
        "What I'd Tell Someone Starting From Scratch",
        "The Mistake I Made in the First Month",
        "How My Routine Changed After Figuring This Out",
    ],
    "food-combo": [
        "Why I Switched to Taking it After Dinner",
        "The Small Meal Context: What Changed My Results",
        "My Practical Guide to Food Pairing",
        "What I Stopped Eating Simultaneously",
        "The Meal That Made the Biggest Difference",
        "Why Empty Stomach Was a Bad Idea for Me",
        "What I Eat Now and Why It Works",
        "The Food Timing Shift That Changed Everything",
        "Breakfast vs Dinner: What Actually Worked",
        "Who Should Be Careful About This Pairing",
    ],
    "side-effects": [
        "The Reality: What It Actually Felt Like",
        "Common Hiccups I Noticed at First",
        "Why It Might Disrupt Your Evening Routine",
        "Learning to Listen to My Body's Signals",
        "What Surprised Me After the First Two Weeks",
        "The Night I Almost Quit (And Why I Didn't)",
        "Who Should Be Extra Cautious With This",
        "How I Managed the Rough Adjustment Period",
        "What Cleared Up On Its Own vs What Didn't",
        "Signs That It's Not Right for Your Body",
    ],
    "antagonism": [
        "Why I No Longer Combine These Two",
        "The Real-World Conflict I Encountered",
        "What the Experience Taught Me",
        "Better Alternatives I Found Instead",
        "The Day I Realized Something Was Off",
        "What Happens When You Get This Wrong",
        "The Safer Approach I Use Now",
        "Who Might Actually Be Fine Combining Them",
        "What I Wish I'd Known Before Starting",
        "How Long It Took to Notice the Problem",
    ],
    "recipe": [
        "The Simple Logic Behind My Daily Routine",
        "Exactly How I Prepare It Each Morning",
        "My Observations on Timing and Results",
        "How I Adjust During Stressful Weeks",
        "The Lazy Version I Use When Traveling",
        "What My Morning Looks Like Now",
        "Why I Keep It Simple on Most Days",
        "The One Preparation Mistake I Made Early On",
        "What Changes When Work Gets Busy",
        "How I Know It's Actually Working",
    ],
    "mechanism": [
        "What Seems to Happen Inside (In Plain English)",
        "Why Consistent Use Mattered More Than the Dose",
        "Practical Results Over Scientific Theory",
        "How it Changed My Afternoon Energy",
        "The Science Part — Kept Short, I Promise",
        "Why I Stopped Trying to Understand Everything",
        "What the Research Actually Told Me",
        "How Long Before I Noticed Anything Real",
        "The Part That Surprised Me Most",
        "What Changed and What Didn't",
    ],
    "protocol": [
        "My New Daily Routine and Timing",
        "The Common Mistakes I Made at the Start",
        "Tracking My Progress: The One Week Shift",
        "Long-Term Safety: What I'm Watching For",
        "How My Approach Changed Over Three Months",
        "The Version I Stick To Most Mornings",
        "What I Do Differently on Bad Weeks",
        "The Minimal Setup That Actually Works",
        "Why I Simplified After Overcomplicating It",
        "Who Should Start Slower Than I Did",
    ],
    "comparison": [
        "Which One Actually Worked Better for Me?",
        "Morning vs Night: The Comparison",
        "Cost and Practicality: My Choice",
        "Decision Guide: Who Should Try Which",
        "The Head-to-Head I Ran Over Four Weeks",
        "What I'd Choose Again If Starting Over",
        "The Subtle Difference Nobody Mentions",
        "Which One Quit Working First",
        "What Price Has to Do With My Choice",
        "The Version That Surprised Me Most",
    ],
    "deficiency": [
        "The Silent Symptoms I Ignored",
        "Who Runs Low More Often Than They Think",
        "Food vs Supplements: My Strategy",
        "How Long Until I Felt a Difference",
        "The Signs I Kept Dismissing as Tiredness",
        "What Got Better and What Stayed the Same",
        "Why Blood Tests Changed My Thinking",
        "How I Eat Differently Now",
        "The Recovery Timeline That Was Slower Than Expected",
        "Who Should Get Tested Before Supplementing",
    ],
    "timing": [
        "Why Timing Changed Everything for Me",
        "My Morning vs Evening Observations",
        "Food Windows and My Daily Schedule",
        "Practical Tips for Better Results",
        "The Experiment I Ran Over Six Weeks",
        "What Early Morning Actually Did for Me",
        "Why I Stopped Taking It Before Bed",
        "The Timing Shift That Made the Difference",
        "How My Energy Pattern Changed With the Clock",
        "What I'd Test First If I Were Starting Over",
    ],
}

# ============================================================
# 아키타입 설정 (Style & Depth)
# ============================================================
# ARCHETYPE_CONFIGS deprecated in favor of ARCHETYPES

def get_sections_for_type(topic_type, count):
    if topic_type == "comprehensive_guide":
        # ── 비율 기반 템플릿 선택 ─────────────────────────────────────────
        # 누적 사용 횟수 로드
        _usage_path = META_DIR / "guide_template_usage.json"
        try:
            usage = json.loads(_usage_path.read_text(encoding="utf-8"))
        except Exception:
            usage = {}
        for k in COMPREHENSIVE_GUIDE_TEMPLATES:
            usage.setdefault(k, 0)

        total_used = sum(usage.values()) or 1

        # deficit = 목표비율 - 실제비율 (높을수록 더 써야 함)
        deficits = {
            k: GUIDE_TEMPLATE_RATIOS.get(k, 0) - (usage[k] / total_used)
            for k in COMPREHENSIVE_GUIDE_TEMPLATES
        }

        # 양수 deficit만 후보로 (모두 음수면 전체 대상)
        pos = {k: max(0.0, d) for k, d in deficits.items()}
        total_w = sum(pos.values())
        if total_w < 1e-9:
            # 모든 템플릿이 목표 달성 → deficit 가장 큰 것부터 가중치
            pos = {k: max(0.0, d + 0.5) for k, d in deficits.items()}
            total_w = sum(pos.values())

        keys = list(pos.keys())
        weights = [pos[k] for k in keys]
        chosen_key = random.choices(keys, weights=weights, k=1)[0]
        tmpl = COMPREHENSIVE_GUIDE_TEMPLATES[chosen_key]

        # 사용 횟수 업데이트
        usage[chosen_key] += 1
        try:
            _usage_path.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        # Writer 프롬프트용 저장 (톤 주입에 사용)
        try:
            (META_DIR / "last_guide_template.json").write_text(
                json.dumps({"template": chosen_key, "label": tmpl["label"]}, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

        # 비율 현황 로그
        _ratio_log = " | ".join(
            f"{k.split('_')[0]}({usage[k]}/{GUIDE_TEMPLATE_RATIOS.get(k,0)*100:.0f}%)"
            for k in GUIDE_TEMPLATE_RATIOS
        )
        logging.info(f"  [Guide Template] 선택: {tmpl['label']} ({chosen_key})")
        logging.info(f"  [Guide Template] 누적 비율: {_ratio_log}")
        return list(tmpl["sections"])

    pool = SECTION_POOLS.get(topic_type, SECTION_POOLS["synergy"])
    return random.sample(pool, min(count, len(pool)))

def detect_topic_type(topic):
    t = topic.lower()
    # [v6.0] 완전 가이드 마커 최우선 감지
    if any(x in t for x in ["[guide]", "complete guide", "comprehensive guide", "ultimate guide", "everything about", "deep dive guide"]):
        return "comprehensive_guide"
    if any(x in t for x in ["vs ", "versus", "compare", "or "]):          return "comparison"
    if any(x in t for x in ["side effect", "warning", "risk", "danger"]):  return "side-effects"
    if any(x in t for x in ["never", "avoid", "block", "antagonist"]):     return "antagonism"
    if any(x in t for x in ["recipe", "food", "eat", "meal", "cook"]):     return "recipe"
    if any(x in t for x in ["deficiency", "deficient", "low ", "lacking"]): return "deficiency"
    if any(x in t for x in ["when to take", "timing", "morning", "evening"]): return "timing"
    if any(x in t for x in ["protocol", "how to", "guide", "dosage"]):     return "protocol"
    if any(x in t for x in ["mechanism", "how it works", "pathway", "receptor"]): return "mechanism"
    if any(x in t for x in ["and ", "synergy", "stack", "combine", "with"]): return "synergy"
    return random.choices(
        list(SECTION_POOLS.keys()),
        weights=[25,15,8,8,8,8,8,8,6,6], k=1
    )[0]

# ============================================================
# 하드코딩 DB
# ============================================================
# 가이드 포스팅 전환 이후 하드코딩 링크 사용 안 함 — published_links.json 기반으로 자동 관리
INTERNAL_LINKS = []

PMID_DB = {
    "magnesium":   ["28709534","26187077","21753063","31850742","28196771"],
    "vitamin":     ["20542256","24497545","29747546","33578876"],
    "omega":       ["24470182","28068728","21040626"],
    "choline":     ["22071706","28413816","18681988","22951317"],
    "creatine":    ["29704637","16416332","14561278"],
    "theanine":    ["18296328","17182482","26869148","22214254"],
    "lion":        ["28677492","27350344"],
    "bacopa":      ["12093601","28230234"],
    "quercetin":   ["31398966","32305264"],
    "glutathione": ["29908994","26633317"],
    "probiotic":   ["28914794","24997031"],
    "coq10":       ["25636661","21224905"],
    "nmn":         ["30836083"],
    "ashwagandha": ["32818573","28829155"],
    "collagen":    ["30681787","26893626"],
    "default":     ["28709534","26187077","24470182","21753063"],
}

LABEL_DB = {
    "default": ["Supplements","NordicHealth","Nootropics","BrainHealth","NutriStackLab"],
}

# About the Author 바이오 변형 풀 — 반복 패턴 방지
_AUTHOR_BIO_VARIANTS = [
    "Every article on NutriStack Lab reflects his real-world testing — not medical advice.",
    "His writing documents personal experiments, not clinical recommendations.",
    "These posts are personal notes from ongoing testing — not a substitute for professional advice.",
    "Everything here is first-person experience. Nothing here is medical guidance.",
    "He writes from his own routine, not from a lab — always personal, never prescriptive.",
    "Each post captures what he actually tried, not what studies promise.",
    "His notes are honest accounts of what worked and what didn't — not health recommendations.",
]

NUTRIENT_RELATIONS = {
    "magnesium":          ["vitamin d","vitamin d3","zinc","l-theanine","sleep","omega","calcium","k2"],
    "vitamin d":          ["magnesium","vitamin k","k2","omega","calcium","boron","zinc","immune"],
    "vitamin d3":         ["magnesium","vitamin k","k2","omega","calcium","boron","zinc","immune"],
    "omega":              ["vitamin d","magnesium","epa","dha","brain","inflammation","heart"],
    "zinc":               ["quercetin","vitamin c","immune","magnesium","testosterone","copper"],
    "l-theanine":         ["caffeine","creatine","magnesium","sleep","focus","alpha wave","gaba"],
    "creatine":           ["alpha-gpc","l-theanine","brain","atp","cognitive","muscle","energy"],
    "alpha-gpc":          ["creatine","choline","cdp","brain","acetylcholine","memory","focus"],
    "lion":               ["bacopa","ngf","brain","neuroplasticity","cognitive","nerve growth"],
    "bacopa":             ["lion","ashwagandha","memory","stress","cognitive","adaptogen"],
    "collagen":           ["vitamin c","glucosamine","msm","joint","skin","bone","hyaluronic"],
    "glucosamine":        ["msm","collagen","joint","chondroitin","cartilage","inflammation"],
    "msm":                ["glucosamine","collagen","vitamin c","sulfur","joint","connective"],
    "quercetin":          ["zinc","vitamin c","immune","inflammation","antiviral","elderberry"],
    "vitamin c":          ["quercetin","glutathione","collagen","immune","antioxidant","iron"],
    "glutathione":        ["vitamin c","nac","selenium","antioxidant","detox","liver","immune"],
    "probiotics":         ["prebiotics","gut","brain","immune","microbiome","inflammation"],
    "nmn":                ["resveratrol","nad","coq10","aging","longevity","mitochondria"],
    "coq10":              ["pqq","nmn","nad","mitochondria","energy","heart","ubiquinol"],
    "pqq":                ["coq10","nmn","mitochondria","bdnf","cognitive","energy"],
    "berberine":          ["alpha lipoic","metformin","insulin","glucose","metabolic","ampk"],
    "ashwagandha":        ["rhodiola","magnesium","cortisol","stress","adaptogen","testosterone"],
    "boron":              ["vitamin d","testosterone","magnesium","shbg","bone","estrogen"],
    "phosphatidylserine": ["omega","dha","brain","cortisol","memory","cognitive","stress"],
    "rhodiola":           ["ashwagandha","adaptogen","fatigue","stress","endurance","cortisol"],
}

# ============================================================
# [v5.4] BANNED_PHRASES — YMYL 안전 수정
# ============================================================
# 수정 원칙:
#   ✅ 과장/단정 AI 표현 → 제거
#   ✅ AI 리듬 패턴 → 제거
#   ❌ 과학 언어(research suggests/studies indicate) → 유지 (YMYL 필수)
#   ❌ 너무 광범위한 단어 치환(optimize/improve/ensures) → 제거 (의도치 않은 치환 방지)
BANNED_PHRASES = {
    # [v5.9] AdSense Integrity Blacklist
    "surprisingly": "as it turns out",
    "magic pills": "supplements",
    "the takeaway": "what I learned",
    "makes all the difference":         "is a key part of the process",
    "magic bullet":                     "simple solution",
    "holistic approach": "comprehensive way",
    "works wonders": "is quite effective",
    "elucidate": "show",
    "boost": "support",
    "maximize": "improve",
    "comprehensive guide": "practical guide",
    "ultimate guide": "real-world guide",
    "in today's world": "currently",

    # AI 과장/단정 표현 및 오타 (v5.6 통합)
    "unlock your potential":           "optimize your output",
    "unlock your cognitive potential":  "reach cognitive peak",
    "unlock":                           "access",
    "game-changer":                     "significant advancement",
    "delve into":                       "examine",
    "dive into":                        "explore",
    "let's explore":                    "here is",
    "in today's fast-paced world":      "when life gets demanding",
    "it's important to note":           "worth noting",
    "it is important to note":          "worth noting",
    "mental dominance":                 "cognitive performance",
    "dramatically":                     "noticeably",
    "revolutionary":                    "newer",
    "unleash":                          "activate",
    "breakthrough":                     "recent discovery",
    "will make you":                    "may help you",
    "guarantees":                       "has been associated with",
    "proven to":                        "shown in studies to",
    "synergistic effect":               "combined effect",
    "synergistic":                      "complementary",
    "in conclusion":                    "in short",
    "to wrap up":                       "in short",
    "to summarize":                     "in short",
    "furthermore":                      "also",
    "moreover":                         "and",
    "nevertheless":                     "still",
    "it is worth noting that":          "notably",
    "it's worth noting that":           "notably",
    "it's worth noting":                "notably",
    "as mentioned above":               "as covered earlier",
    "in this article":                  "here",
    "the purpose of this":              "this",
    "by incorporating":                 "by using",
    "this holistic approach":           "this approach",
    "remember, consistency is key":     "",
    "consistency is key":               "consistency matters",
    "honestly":                         "in my experience",
    "surprisingly": "as it turns out",
    "oddly enough":                     "interestingly",
    "interestingly enough":             "actually",
    "anecdotally":                      "from what I've seen",
    "in practice":                      "in real life",
    "essentially":                      "basically",
    "notably":                          "also",
    "protocol":                         "routine",
    "optimization":                     "finding",
    "synergy":                          "pairing",
    "architecture":                     "setup",
    "framework":                        "logic",
    "landscape":                        "area",
    "lipophilic":                       "fat-loving",
    "enterocytes":                      "gut cells",
    "micelles":                         "absorption units",
    "modulation":                       "adjustment",
    "works well together":              "pairs well",
    "helps deliver benefits":           "helps",
    "complementaryally":                "complementary",
    "optimize":                         "improve",
    "delve":                            "look",
    "leverage":                         "use",
    "tailored":                         "suited",
    "facilitate":                       "help",
    "utilize":                          "use",
    "underscores":                      "shows",
    "elucidates":                       "explains",
    "demonstrated measurable improvements relevant to this topic": "showed relevant findings",
    "it is worth mentioning":           "",
    "it's worth mentioning":            "",

    "delivers benefits throughout":     "complements broader habits",
    "pair naturally":                   "complement each other",
    "the bottom line?":                 "in short,",
    "the bottom line":                  "in short",

    "i used to think":                  "at first",
    "complementary":                    "complementary",
    "taking vitamin":                   "this routine",
    "it's not rocket science":          "it's pretty straightforward",
    "it is not rocket science":         "it's not complicated",
    "it's actually quite simple":       "it's pretty straightforward",
    "it is actually quite simple":      "it's not complicated",
    "what i found was":                 "over time i noticed",
    "here's the catch":                 "one thing worth noting",
    "here\u2019s the catch":             "one thing worth noting",
    # [v5.9.4] here's the kicker — 직선/컬리 아포스트로피 둘 다 차단
    "here's the kicker":               "one thing worth noting",
    "here\u2019s the kicker":           "one thing worth noting",
    "here's the thing":                "the point is",
    "here\u2019s the thing":            "the point is",
    # [v5.9.4] 건강 과장 표현 blacklist
    "game changer":                    "useful option",
    "works wonders for":               "is quite effective for",
    "work wonders":                    "help significantly",
    "clearer skin":                    "improved skin texture",
    "sharper brain":                   "better mental clarity",
    "better sleep":                    "more consistent sleep",
    "energy boost":                    "less fatigue",
    "noticeable difference":           "gradual change",
    "within days":                     "after consistent use",
    "within a week":                   "after several weeks",
    "within weeks":                    "after consistent use",
    "made all the difference":         "really helped me stay consistent",
    "makes all the difference":        "is a key part of the process",
    "a key part of the process":       "part of my daily routine",
    "meaningful part of the routine":  "part of my daily routine",
    "shine together":                  "work better for me",
    "give my body a support":          "help me feel more stable",
    "give my body support":            "help me feel more stable",
    "Consistency mattered more than I expected": "That seemed to matter more than the dose",
    "work their magic":                "take full effect",
    "works its magic":                 "takes effect",
    "start working its magic":         "start taking effect",
    "felt like magic":                 "felt noticeably smoother",
    "made a big difference":           "really helped me",
    "magic pill":                      "instant fix",
    "energy support":                  "stable afternoon energy",
    "support":                         "help",
    "enhance":                         "help",
    "improve":                         "change",
    "stable energy support":           "steadier energy through the day",
    "research points to one overlooked variable": "the biggest thing i overlooked was timing",
    "works wonders":                   "helps significantly",
    "worked wonders":                  "helped significantly",
    "wasn't":                          "wasn't",
    "It wasn't":                       "It wasn't",
    "consistency matters":             "consistency is key",
    "Consistency matters":             "Consistency is key",
    # [v5.9.4] Nordic health optimization 랜덤화 대상 추가
    "nordic health optimization":      "nordic health approach",
    "the key is":                       "what helped most was",
    "the key takeaway":                 "the main point",
    "complement broader health habits": "fit into a daily routine",
    "complements broader habits":       "fits into a daily routine",
    "complement broader":               "fit into broader",
    "studies indicate":                 "research suggests",
    "clinical findings suggest":        "some evidence indicates",
    "a key part of the process":        "meaningful part of the routine",
    "meaningful part of the routine":  "part of my daily routine",
    "help change focus":                "clear brain fog",
    "helps change focus":               "helps me concentrate",
    "immune help":                      "immune support",
    "pumpkin seeds":                    "oatmeal and walnuts",
    "nordic winter months":             "colder months",
    "magic pill":                       "instant fix",
    "magic hour":                       "ideal time",
    "change everything":                "make things more consistent",
    "optimal timing":                   "timing that worked",
    "changement":                       "change",
    "changements":                      "changes",
    "consistency is king":              "staying consistent",
    "In short is":                      "In short",
    "magic window":                     "ideal timing for me",
    "flickering candle":                "fading focus",
    "flickering flame":                 "low energy",
    "Trust me":                         "In my experience",
    "may inhibit zinc":                 "might affect zinc comfort",
    "And Routine":                      "My zinc routine",
    "And Pairing":                      "My daily stack",
    "elevate your":                     "improve your",
    "embark on":                        "start",
    "tapestry of":                      "variety of",
    "holistic approach":                "total routine",
    "in today's world":                 "nowadays",
    "it's crazy how":                   "it was surprising that",
    "the results were clear":           "I noticed a pattern",
    "might seem small":                 "felt minor",
    "make a big difference":            "had an impact",
    "give it a shot":                   "try it",
    "like magic":                       "effectively",
    "That's basically useless": "that didn't seem to work well for me",
    "that's basically useless": "that didn't seem to work well for me",
    "makes you stronger": "seemed to help with strength",
    "helps you recover faster": "seemed to help with recovery",
    "basically wasting": "probably not getting the full benefit from",
    "healed my chronic": "helped with my",
    "Healed My Chronic": "Helped With My",
    "crashes disappeared": "crashes became less noticeable",
    "brain fog lifted": "I felt mentally clearer",
    "Brain fog lifted": "I felt mentally clearer",
    "pain disappeared": "pain became less noticeable",
    "neither one is getting properly absorbed": "absorption of both may be affected",
    "you can feel simultaneously": "it seemed like I was feeling",

    # [v10.1] 메커니즘 AI 흔적 — SAMe/NAD 분석에서 추출
    "rewiring neurotransmitters":           "gradually affecting mood and focus patterns",
    "reverse aging at molecular level":     "what some researchers are exploring with cellular energy",
    "at the molecular level":               "in ways I don't fully understand",
    "physiological response discussed here": "what I described above",

    # [v10.1] YMYL 직접 증상 해결 — D3+K2 분석에서 추출
    "the chest pain stopped":               "around that time, the discomfort gradually became less noticeable",
    "chest pain stopped":                   "the discomfort became less noticeable over time",
    "the pain stopped":                     "the discomfort became less noticeable",
    "calcium could accumulate in the wrong places": "some discussions suggested K2 may help direct calcium utilization",

    # [v10.1] AI 메타포 — NAD 분석에서 추출
    "broken battery":                       "drained feeling",
    "party in a vacuum":                    "effort that didn't seem to add up",

    # [v10.1] AI reflective loop 패턴 — NAD 분석에서 추출
    "not a miracle":                        "not an overnight fix",
    "it's not a miracle":                   "it's not an overnight fix",
    "not a magic":                          "not an instant",

}

# ============================================================
# 링크 DB 함수
# ============================================================
def load_links_db():
    LINKS_DB_FILE.parent.mkdir(exist_ok=True, parents=True)
    if LINKS_DB_FILE.exists():
        try: return json.loads(LINKS_DB_FILE.read_text(encoding='utf-8'))
        except: return []
    return []

def save_links_db(db: list):
    LINKS_DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')

def save_link_to_db(title, url, topic, nutrients, post_id="", score=0.0, html_path="", template="", topic_type=""):
    db = load_links_db()
    if any(l.get("url","") == url for l in db): return
    db.append({"title": title, "url": url, "topic": topic,
                "nutrients": nutrients, "date": datetime.now().strftime("%Y-%m-%d"),
                "category": detect_category(topic), "template": template,
                "post_id": post_id, "score": round(score, 3), "html_path": html_path,
                "topic_type": topic_type})
    LINKS_DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
    logging.info(f"  🔗 링크 DB 저장: {title[:40]}")

GUIDE_SERIES_START = datetime(2026, 5, 24)  # NMN 가이드 시작일 — 이후 포스팅은 삭제 금지

def delete_related_thin_posts(guide_topic, guide_url, nutrients):
    """가이드 발행 시 같은 영양소 관련 기존 얇은 글 Blogger에서 삭제.
    GUIDE_SERIES_START(2026-05-24) 이후 발행된 포스팅은 삭제하지 않음.
    """
    if not nutrients:
        return
    db = load_links_db()
    svc = get_blogger_service()
    keywords = [n.lower() for n in nutrients]
    deleted, skipped = [], []

    for entry in db:
        if entry.get("url") == guide_url:
            continue  # 방금 발행한 가이드는 스킵
        # 가이드 포스팅 보호 (comprehensive_guide 타입 또는 제목에 Complete Guide 포함)
        if entry.get("topic_type") == "comprehensive_guide":
            continue
        if "complete guide" in entry.get("title", "").lower():
            continue
        # 날짜 필터: 가이드 시리즈 시작일 이후 포스팅은 삭제 금지
        pub_str = entry.get("published_at", "") or entry.get("date", "")
        if pub_str:
            try:
                pub_dt = datetime.fromisoformat(pub_str[:19])
                if pub_dt >= GUIDE_SERIES_START:
                    skipped.append(entry.get("title", "")[:30] + " (보호)")
                    continue
            except Exception:
                pass
        title_lower = entry.get("title", "").lower()
        topic_lower = entry.get("topic", "").lower()
        # 영양소 키워드가 제목이나 토픽에 포함된 경우
        if any(kw in title_lower or kw in topic_lower for kw in keywords):
            pid = entry.get("post_id", "")
            if pid and svc:
                try:
                    svc.posts().delete(blogId=BLOG_ID, postId=pid).execute()
                    deleted.append(entry.get("title", "")[:50])
                    logging.info(f"  🗑️ 삭제: {entry.get('title','')[:50]}")
                    report_to_discord("정리", f"🗑️ 구글 삭제: {entry.get('title','')[:50]}")
                except Exception as e:
                    logging.warning(f"  삭제 실패 ({entry.get('title','')[:30]}): {e}")
                    skipped.append(entry.get("title", "")[:30])
            else:
                skipped.append(entry.get("title", "")[:30] + " (post_id 없음)")

    # DB에서도 삭제된 글 제거
    if deleted:
        new_db = [e for e in db if e.get("title", "")[:50] not in deleted]
        LINKS_DB_FILE.write_text(json.dumps(new_db, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.info(f"  🗑️ 관련 글 {len(deleted)}개 삭제 완료 (스킵: {len(skipped)}개)")

AUDIT_QUEUE_FILE = BASE_DIR.parent / "batch" / "audit_queue.json"

def add_to_audit_queue(title, url, post_id, html_path, score, topic):
    """발행 완료 포스팅을 1차 감사 대기열에 추가."""
    try:
        AUDIT_QUEUE_FILE.parent.mkdir(exist_ok=True, parents=True)
        queue = []
        if AUDIT_QUEUE_FILE.exists():
            try: queue = json.loads(AUDIT_QUEUE_FILE.read_text(encoding="utf-8"))
            except: queue = []
        if any(e.get("url") == url for e in queue):
            return  # 중복 방지
        queue.append({
            "title": title,
            "url": url,
            "post_id": post_id,
            "html_path": str(html_path),
            "score_pre": round(score, 3),
            "score_1차": None,
            "score_2차": None,
            "phase": "pending_1차",
            "topic": topic,
            "published_at": datetime.now().isoformat()
        })
        AUDIT_QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.info(f"  📋 감사 대기열 추가: {title[:40]} (사전점수 {score:.0%})")
    except Exception as e:
        logging.warning(f"  감사 대기열 추가 실패: {e}")

def detect_category(topic):
    t = topic.lower()
    if any(k in t for k in ["cognitive","brain","memory","focus","lion","bacopa","creatine","choline","theanine"]): return "COGNITIVE"
    elif any(k in t for k in ["vitamin d","magnesium","zinc","omega","k2","boron"]): return "FUNDAMENTAL"
    elif any(k in t for k in ["nmn","coq10","pqq","berberine","nad","mitochondria"]): return "METABOLIC"
    elif any(k in t for k in ["collagen","glucosamine","msm","joint","bone","skin"]): return "STRUCTURAL"
    elif any(k in t for k in ["probiotic","immune","quercetin","vitamin c","glutathione"]): return "IMMUNE"
    return "GENERAL"

def extract_nutrients_from_topic(topic):
    # v5.5: NUTRIENT_RELATIONS 키값을 기준으로 추출하되, 'common', 'mistakes' 등 오염 단어 제외
    black_list = ["common", "mistakes", "tips", "avoid", "timing", "guide", "protocol"]
    found = []
    t_lower = topic.lower()
    for k in NUTRIENT_RELATIONS.keys():
        if k in t_lower and k not in black_list:
            found.append(k)
    return list(set(found))[:5]

def _is_guide_post(entry: dict) -> bool:
    """가이드 포스팅 판단 — topic 또는 제목에 'guide' 포함 여부로만 판단."""
    topic = entry.get("topic", "").lower()
    title = entry.get("title", "").lower()
    return "guide" in topic or "complete guide" in title or "comprehensive guide" in title

def find_related_links(topic, count=5):
    db = load_links_db()
    # 모든 발행 포스팅 후보 (가이드 필터 제거 — 개인 경험 제목도 포함)
    all_links = list(INTERNAL_LINKS) + db
    # 중복 URL 제거
    seen = set()
    deduped = []
    for e in all_links:
        u = e.get("url", "")
        if u not in seen:
            seen.add(u)
            deduped.append(e)
    all_links = deduped
    topic_nutrients = extract_nutrients_from_topic(topic)
    topic_lower = topic.lower()
    scored = []
    for link in all_links:
        score = 0
        link_title    = link.get("title","").lower()
        link_nutrients= [n.lower() for n in link.get("nutrients", [])]
        link_topic    = link.get("topic","").lower()

        # 같은 주제 제외
        if any(nut in link_title for nut in topic_nutrients) and \
           all(nut in link_title for nut in topic_nutrients):
            continue  # 현재 글과 동일 영양소 조합 → 스킵

        # 1순위: 시너지/반감 관계 영양소 포함 포스팅
        for nut in topic_nutrients:
            for rel in NUTRIENT_RELATIONS.get(nut, []):
                if rel in link_title or rel in link_topic:
                    score += 3
            # 해당 영양소 직접 포함
            if nut in link_title or nut in link_topic:
                score += 2
            if nut in link_nutrients:
                score += 1

        if score > 0:
            scored.append((score, link))
    scored.sort(key=lambda x: x[0], reverse=True)

    bad_markers = [
        "here are", "proposed title", "options:", "the is protocol",
        "the and protocol", "the with protocol", "why and vitamin",
        "best:", "simpler way to think about ginger", "practical look at why and",
        "when people prefer when", "nutrient vs and", "the is ",
        "blood: timing", "when people prefer", " and and ", "ps and omega",
        "alpha and gpc", "dup and ", "maximize and ", "vitamin and d",
        "never combine why", "after vs vitamin", "vs vitamin", "my choice after testing",
        "vitamin and d3", "when i take common", "when people prefer",
    ]
    def _is_bad(entry):
        t = entry.get("title", "").lower()
        if len(t) < 15: return True
        if any(m in t for m in bad_markers): return True
        if t.startswith(("write ", "task ", "here ", "best:", "the is ")): return True
        return False

    # scored 결과에도 오염 제목 필터 적용
    selected = [link for _, link in scored[:count] if not _is_bad(link)]

    if len(selected) < count:
        remaining = [l for l in all_links if l not in selected]
        cleaned_data = [e for e in remaining if not _is_bad(e)]
        random.shuffle(cleaned_data)
        selected.extend(cleaned_data[:count-len(selected)])
    link_count = min(count, len(selected))
    logging.info(f"  🕸️ 관련 링크 {link_count}개 선택")
    
    # [v5.9.9.9] 링크 제목 인격화 (Footprint 제거)
    final_links = []
    for l in selected[:link_count]:
        new_l = l.copy()
        new_l["title"] = humanize_link_title(l.get("title", ""))
        final_links.append(new_l)
        
    return final_links

def humanize_link_title(title):
    # [v5.9.9.9] AI 단어들을 부드러운 인간 표현으로 교체
    replacements = {
        "Protocol": "Routine",
        "Optimization": "Strategy",
        "Synergy": "Pairing",
        "Mechanism": "Science",
        "Advanced": "Practical",
        "Comprehensive": "Real-world",
        "Essential": "Key",
        "Nordic Stack": "My Daily Routine",
        "Immune Acceleration Stack": "Immune Support Routine",
        "The Master": "My Simple",
        "Ultimate": "Best",
        "Common": "",
        "Mistakes": "Errors",
    }
    new_title = title
    for k, v in replacements.items():
        new_title = re.sub(rf'(?i)\b{k}\b', v, new_title)
    
    # 중복 공백 제거 및 정리
    new_title = re.sub(r'\s+', ' ', new_title).strip()
    return new_title

def _clean_topic_for_dup(t):
    t = re.sub(r'^#\s*', '', t.strip())
    t = re.sub(r'\ntype:.*', '', t, flags=re.IGNORECASE)
    return t.lower().strip()

def is_duplicate(topic):
    topic_lower = _clean_topic_for_dup(topic)
    topic_words = set(re.sub(r'[^\w\s]', ' ', topic_lower).split())
    db   = load_links_db()
    stop = {"the","and","or","a","an","of","for","in","with","vs","is","your","how","why",
            "nordic","protocol","stack","science","ultimate"}
    t_words = topic_words - stop
    for entry in db:
        existing_title = entry.get("title","").lower()
        existing_topic = _clean_topic_for_dup(entry.get("topic",""))
        e_words_title  = set(re.sub(r'[^\w\s]', ' ', existing_title).split()) - stop
        e_words_topic  = set(re.sub(r'[^\w\s]', ' ', existing_topic).split()) - stop
        
        # 제목이나 주제어 중 하나라도 90% 이상 겹치면 중복
        for e_words in [e_words_title, e_words_topic]:
            if not t_words or not e_words: continue
            overlap = len(t_words & e_words) / max(len(t_words), len(e_words))
            if overlap >= 0.9:
                logging.warning(f"  🔴 중복 감지 (Overlap: {overlap:.1%}): {topic[:40]}")
                return True, entry.get("title","")
    return False, None

# ============================================================
# 에이전트 / 레슨 / Discord
# ============================================================
def report_to_discord(agent, message):
    try:
        webhook_url = ""
        config_file = BASE_DIR / "config.json"
        if config_file.exists():
            data = json.loads(config_file.read_text(encoding='utf-8'))
            webhook_url = data.get("webhook_url", "")
        if not webhook_url and DISCORD_WEBHOOK_FILE.exists():
            data = json.loads(DISCORD_WEBHOOK_FILE.read_text(encoding='utf-8'))
            webhook_url = data.get("webhook_url", "")
        if webhook_url:
            requests.post(webhook_url,
                json={"content": f"🏛️ **[{agent}]** {message}"}, timeout=5)
    except: pass

def load_agent(filename):
    path = PROMPT_DIR / filename
    content = ""
    if path.exists(): 
        content = path.read_text(encoding='utf-8')
    else:
        content = "You are a professional health content agent."
    
    # [v5.9.9.9] 모든 에이전트에게 공통 지침서(Source of Truth) 및 실패 사례 주입
    for manual_name in ["NutriStack_Source_of_Truth.md", "FAILURE_REINFORCEMENT.md"]:
        manual_path = PROMPT_DIR / manual_name
        if manual_path.exists():
            manual_content = manual_path.read_text(encoding='utf-8')
            content = f"{content}\n\n{manual_content}"
        
    return content

def send_daily_briefing(topics):
    try:
        # v5.4.1: 중복 전송 방지 로직
        briefing_flag = META_DIR / "last_briefing.json"
        today_str = datetime.now().strftime("%Y-%m-%d")
        if briefing_flag.exists():
            try:
                flag = json.loads(briefing_flag.read_text(encoding='utf-8'))
                if flag.get("date") == today_str:
                    logging.info("  ⏭️ 오늘 이미 브리핑을 전송했습니다.")
                    return
            except: pass

        trend_sys = load_agent("trend_hunter.md")
        trend = ask_ai(
            f"오늘 발행 예정 주제 분석: {json.dumps(topics, ensure_ascii=False)}\n"
            f"각 주제의 선정 이유와 예상 반응을 상세히 한국어로 설명하라.",
            trend_sys, LIGHT_MODEL, timeout=120
        )
        
        # 메시지 조립 (300자 제한 해제)
        msg_header = f"📋 **NutriStack 일일 브리핑 | {today_str}**\n\n"
        msg_plan = f"📅 **발행 계획:**\n" + "".join([f"⏰ [{t.get('time','')}] **{t.get('topic','')}**\n" for t in topics])
        msg_trend = f"\n📊 **트렌드 분석:**\n{trend}"
        
        full_msg = msg_header + msg_plan + msg_trend
        
        # Discord 전송 (글자 수 제한 처리 - 1900자씩 분할)
        if len(full_msg) > 1900:
            for i in range(0, len(full_msg), 1900):
                report_to_discord("브리핑", full_msg[i:i+1900])
        else:
            report_to_discord("브리핑", full_msg)
            
        # 전송 기록 저장
        briefing_flag.write_text(json.dumps({"date": today_str, "time": datetime.now().isoformat()}, indent=2), encoding='utf-8')
        logging.info("✅ 일일 브리핑 전송 완료")
    except Exception as e:
        logging.warning(f"브리핑 오류: {e}")

def post_to_pinterest_auto(title, url, image_url=None):
    try:
        pinterest_script = BASE_DIR / "pinterest_poster.py"
        if not pinterest_script.exists(): return
        import importlib.util
        spec = importlib.util.spec_from_file_location("pinterest_poster", pinterest_script)
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        if pm.post_to_pinterest(title, url, image_url):
            logging.info("  ✅ Pinterest 핀 생성!")
            report_to_discord("Pinterest", f"✅ 핀!\n{title[:40]}")
    except Exception as e:
        logging.warning(f"  ⚠️ Pinterest 오류: {e}")

def post_to_twitter_auto(title, url, image_url=None, tweet_text=None):
    try:
        twitter_script = BASE_DIR / "twitter_poster.py"
        if not twitter_script.exists(): return
        import importlib.util
        spec = importlib.util.spec_from_file_location("twitter_poster", twitter_script)
        tm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tm)
        if tm.post_to_twitter(title, url, image_url, tweet_text):
            logging.info("  ✅ Twitter 트윗!")
            report_to_discord("Twitter", f"✅ 트윗!\n{title[:40]}")
    except Exception as e:
        logging.warning(f"  ⚠️ Twitter 오류: {e}")

def load_lessons():
    if LESSONS_FILE.exists():
        try: return json.loads(LESSONS_FILE.read_text(encoding='utf-8'))
        except: return {}
    return {}

def save_lessons(lessons):
    LESSONS_FILE.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding='utf-8')

def load_core_lessons():
    if CORE_LESSONS_FILE.exists():
        try: return json.loads(CORE_LESSONS_FILE.read_text(encoding='utf-8'))
        except: return {}
    return {}

def save_core_lessons(core):
    CORE_LESSONS_FILE.write_text(json.dumps(core, ensure_ascii=False, indent=2), encoding='utf-8')

def _lesson_similarity(a: str, b: str) -> float:
    """두 레슨 문자열의 키워드 겹침 비율 (0.0~1.0)."""
    wa = set(re.findall(r'\w{3,}', a.lower()))
    wb = set(re.findall(r'\w{3,}', b.lower()))
    if not wa or not wb: return 0.0
    return len(wa & wb) / max(len(wa), len(wb))

def promote_to_core_lessons(lessons: dict) -> dict:
    """agent_lessons에서 count >= 3인 레슨을 core_lessons로 승격."""
    core = load_core_lessons()
    promoted_any = False
    for agent_key, entries in lessons.items():
        if agent_key.endswith("_good"): continue
        for entry in entries:
            if entry.get("count", 1) < 3: continue
            lesson_text = entry.get("lesson", "")
            if not lesson_text: continue
            core.setdefault(agent_key, [])
            already = any(
                _lesson_similarity(lesson_text,
                    c.get("lesson") or c.get("fix") or c.get("issue", "")) >= 0.60
                for c in core[agent_key]
            )
            if already: continue
            core[agent_key].append({
                "lesson": lesson_text[:300],
                "count": entry["count"],
                "promoted_date": datetime.now().strftime("%Y-%m-%d"),
                "first_seen": entry.get("first_seen", datetime.now().strftime("%Y-%m-%d")),
            })
            promoted_any = True
            logging.info(f"  🏆 [Core 승격] {agent_key}: count={entry['count']} → core_lessons")
    if promoted_any:
        save_core_lessons(core)
    return core

def load_agent_with_lessons(filename, topic_type: str = ""):
    base_prompt   = load_agent(filename)
    agent_key     = filename.replace(".md", "")
    lessons       = load_lessons()
    core          = load_core_lessons()

    lessons_block = ""

    # ── [friend_experience] 지인 시점 프롬프트 주입 ───────────────────
    if agent_key == "03_Writer_Gardener" and topic_type == "friend_experience":
        lessons_block += (
            "\n\n## 🧑‍🤝‍🧑 FRIEND EXPERIENCE MODE — PERSONA SHIFT (MANDATORY)\n"
            "This post is written from the perspective of SOMEONE DESCRIBING A FRIEND/COLLEAGUE's experience.\n"
            "YOU ARE NOT THE PERSON WHO TOOK THE SUPPLEMENT — a friend/colleague/gym buddy did.\n\n"
            "MANDATORY RULES:\n"
            "1. The NARRATOR (Erik) observed and learned from their friend's experience\n"
            "2. Use: 'My friend noticed...', 'She told me...', 'He mentioned...', "
            "'A colleague of mine started...', 'Someone at my gym said...'\n"
            "3. Erik's own voice appears as OBSERVER: 'I watched her go through it', "
            "'Hearing her describe it made me pay attention', 'I was skeptical at first'\n"
            "4. The friend is the protagonist — Erik is the narrator/witness\n"
            "5. NO sentences like 'I took X' or 'I noticed X changed' — Erik did NOT take it\n"
            "6. End with Erik's reflection: 'Listening to her changed how I thought about X'\n\n"
            "EXAMPLE OPENING: 'My colleague started taking [nutrient] three months before I gave "
            "it any serious thought. I remember thinking she was overcomplicating her routine. "
            "Then she started describing what she noticed, and I started paying attention.'\n"
        )
        logging.info("  👥 [friend_experience] 지인 시점 프롬프트 주입")

    # ── [Tier 1] 직전 글 미수정 이슈 — 최우선 주입 ───────────────────
    # PPV가 자동 수정 못 한 high/critical 이슈 → Writer가 반드시 회피
    if agent_key == "03_Writer_Gardener":
        _last_ppv_path = META_DIR / "last_ppv_unfixed.json"
        if _last_ppv_path.exists():
            try:
                _last = json.loads(_last_ppv_path.read_text(encoding="utf-8"))
                _age_hrs = (datetime.now() - datetime.fromisoformat(_last["timestamp"])).total_seconds() / 3600
                if _age_hrs < 24 and _last.get("unfixed"):
                    lessons_block += (
                        "\n\n## 🚨 CRITICAL: ISSUES FROM YOUR LAST POST (PPV COULD NOT AUTO-FIX THESE):\n"
                        f"Last post: '{_last.get('title','')}' — final score {_last.get('total','?')}/10\n"
                        "These were NOT fixed automatically. You MUST avoid them in this post:\n"
                    )
                    for _i, _iss in enumerate(_last["unfixed"], 1):
                        lessons_block += f"{_i}. [{_iss['severity'].upper()}] {_iss['description']}\n"
                    logging.info(f"  🚨 [Writer] 직전 글 미수정 {len(_last['unfixed'])}개 최우선 주입")
            except Exception as _e:
                pass

    # ── [Tier 2] 핵심 영구 교훈 — active=true만, 타입 우선 정렬 ──────
    core_entries_all = core.get(agent_key, [])
    # Lifecycle: active=false(휴면)는 제외. active 필드 없는 기존 항목은 active=true 취급
    core_entries = [c for c in core_entries_all if c.get("active", True)]
    dormant_core = len(core_entries_all) - len(core_entries)
    if dormant_core > 0:
        logging.info(f"  💤 [Lifecycle] core_lessons 휴면 {dormant_core}개 제외 (active=false)")

    if topic_type and agent_key == "03_Writer_Gardener":
        def _type_relevance(c):
            t = str(c.get("topic_type","") or c.get("lesson","")).lower()
            if topic_type == "comprehensive_guide" and "guide" in t:
                return 0
            if topic_type != "comprehensive_guide" and ("experience" in t or "longtail" in t):
                return 0
            return 1
        core_entries = sorted(core_entries, key=_type_relevance)

    if core_entries:
        lessons_block += "\n\n## 🏆 CORE PERMANENT LESSONS (ALWAYS APPLY — NEVER IGNORE):\n"
        for i, c in enumerate(core_entries, 1):
            _lesson_text = c.get("lesson") or c.get("fix") or c.get("issue", "")
            _cp = c.get("clean_posts", 0)
            _cp_str = f" [✓{_cp}회 연속 통과]" if _cp >= 5 else ""
            lessons_block += f"{i}. [반복{c.get('count',1)}회{_cp_str}] {_lesson_text}\n"

    # ── [Tier 3] 실패 교훈 — active=true + 타입 우선 정렬 ─────────
    bad_lessons_all = lessons.get(agent_key, [])
    # Lifecycle 필터
    bad_lessons = [l for l in bad_lessons_all if l.get("active", True)]
    dormant_bad = len(bad_lessons_all) - len(bad_lessons)
    if dormant_bad > 0:
        logging.info(f"  💤 [Lifecycle] agent_lessons 휴면 {dormant_bad}개 제외")

    if bad_lessons:
        if topic_type and agent_key == "03_Writer_Gardener":
            type_related = [l for l in bad_lessons if topic_type in str(l.get("lesson","")).lower()]
            other        = [l for l in bad_lessons if l not in type_related]
            recent_bad   = (type_related + other)[-10:]
        else:
            recent_bad = bad_lessons[-10:]
        lessons_block += "\n\n## ⚠️ PAST REJECTION LESSONS (AVOID THESE):\n"
        for i, l in enumerate(recent_bad, 1):
            _l_date = l.get('date') or l.get('added_at', '')
            lessons_block += f"{i}. [{_l_date}] {l.get('lesson','')}\n"

    # ── [Tier 3] 성공 사례 (발행 성공 패턴) ──────────────────────
    good_key     = f"{agent_key}_good"
    good_lessons = lessons.get(good_key, [])
    if good_lessons:
        recent_good = good_lessons[-5:]
        lessons_block += "\n\n## ✅ RECENT SUCCESS PATTERNS (FOLLOW THESE):\n"
        for i, l in enumerate(recent_good, 1):
            _l_date  = l.get('date') or l.get('added_at', '')
            _l_score = l.get('score', None)
            _score_str = f" score={_l_score:.0%}" if isinstance(_l_score, float) else ""
            lessons_block += f"{i}. [{_l_date}]{_score_str} | {l.get('lesson','')}\n"

    # ── Critic B 캘리브레이션 교정 지침 (Critic에만 주입) ─────────
    if "05_Critic" in agent_key:
        _calib_path = BASE_DIR.parent / "batch" / "critic_a_calibration.md"
        if _calib_path.exists():
            try:
                _calib_text = _calib_path.read_text(encoding="utf-8")
                lessons_block += f"\n\n## 🎯 CALIBRATION GUIDELINES (전문가 검토 기반 교정):\n{_calib_text}\n"
                logging.info("  🎯 [Critic] 캘리브레이션 교정 지침 주입 완료")
            except Exception as e:
                logging.warning(f"  [Critic] 캘리브레이션 로드 실패: {e}")

    # ── v7.9 Writer 전용 경고 규칙 ──────────────────────────────
    if agent_key == "03_Writer_Gardener":
        lessons_block += (
            "\n\n## ⚠️ FAT/ABSORPTION WRITING RULES (v7.9+ — MANDATORY):\n"
            "1. If the post title contains 'Timing' or 'Routine': fat/absorption = MAX 2 sentences total.\n"
            "2. Fat-soluble vitamins (K2, D3, A, E, CoQ10): mention 'take with food' ONCE only.\n"
            "3. Fat mention cap: 8 times max per article (excluding 'fat-soluble').\n"
            "4. WATER-SOLUBLE supplements (HMB, SAMe, B12, B6, Vitamin C, Probiotics, Creatine, NMN, Berberine, Zinc, Magnesium): "
            "NEVER say 'take with fat', 'fatty meal', 'fat helps absorption'. These are WATER-SOLUBLE.\n"
            "5. BAD: 'Take SAMe with a fatty meal for absorption.' "
            "GOOD: 'I took it at the same time every day.'\n"
            "6. food mention cap for water-soluble posts: 8 times max. Beyond = absorption guide, not personal story.\n"
            "7. Post narrative must match title: Timing = timing story. Never 70% absorption mechanics.\n"
        )

    # ── S등급 레퍼런스 아티클 (Writer에만 주입) ──────────────────
    if agent_key == "03_Writer_Gardener":
        ref_path = META_DIR / "reference_S_grade.html"
        if ref_path.exists():
            try:
                ref_html = ref_path.read_text(encoding="utf-8")
                # 핵심 구절만 발췌 — Hook + 섹션 2개 + 경험 테이블 + 유머 + YMYL
                _hook_end = ref_html.find("<hr />")
                _excerpt  = ref_html[ref_html.find("<p>My coworker"):_hook_end + 500] if "<p>My coworker" in ref_html else ""
                _table_s  = ref_html.find("<table>")
                _table_e  = ref_html.find("</table>") + 8
                _table    = ref_html[_table_s:_table_e] if _table_s != -1 else ""
                _humor_s  = ref_html.find('"Take with food" does not mean')
                _humor    = ref_html[_humor_s:_humor_s+120] if _humor_s != -1 else ""
                _ymyl     = "I'm not a doctor. I have no credentials. I'm just someone who got annoyed enough to experiment."
                lessons_block += (
                    "\n\n## 🏆 S-GRADE REFERENCE ARTICLE (9.6/10 — MATCH THIS STYLE, NOT THIS CONTENT):\n"
                    "Study this article's VOICE and STRUCTURE. Never copy its content. Adapt the patterns to the new topic.\n\n"
                    f"--- HOOK EXAMPLE ---\n{_excerpt[:800]}\n\n"
                    f"--- EXPERIENCE TABLE EXAMPLE ---\n{_table[:600]}\n\n"
                    f"--- HUMOR EXAMPLE (natural, not forced) ---\n{_humor}\n\n"
                    f"--- YMYL DISCLAIMER EXAMPLE ---\n{_ymyl}\n"
                    "--- END REFERENCE ---\n"
                )
                logging.info("  📖 [Writer] S등급 레퍼런스 아티클 주입 완료")
            except Exception as e:
                logging.warning(f"  [Writer] 레퍼런스 로드 실패: {e}")

    if lessons_block:
        n_core = len(core_entries)
        n_bad  = len(bad_lessons[-10:])
        n_good = len(good_lessons[-5:])
        logging.info(f"  🧠 [{agent_key}] 핵심{n_core}개 + 실패{n_bad}개 + 성공{n_good}개 주입 (총 {n_core+n_bad+n_good}개)")

    # ── [v7.2] Shared Brain 주입 — 모든 에이전트 공통 지식 ────────────────
    try:
        import shared_brain as _sb
        if not _sb.BRAIN_FILE:
            _sb.init(META_DIR)
        _role_map = {
            "03_Writer_Gardener":       "writer",
            "05_Critic_Editor_In_Chief": "critic",
            "02_Researcher_Synergy":    "writer",
            "04_SEO_Optimizer":         "writer",
            "06_Persona_Guardian":      "writer",
        }
        _role = _role_map.get(agent_key, "writer")
        _brain_block = _sb.get_injection(_role)
        if _brain_block:
            lessons_block += _brain_block
    except Exception as _sbe:
        logging.warning(f"  [SharedBrain] 주입 실패 (무시): {_sbe}")

    return base_prompt + lessons_block

def _parse_critic_lessons(critic_result: str) -> list:
    """
    Critic 출력의 LESSONS_START...LESSONS_END 블록을 파싱.
    각 레슨을 {'agent_key', 'lesson', 'issue', 'root_cause', 'fix', 'count'} dict로 반환.
    """
    AGENT_FILE_MAP = {
        "writer":     "03_Writer_Gardener",
        "researcher": "02_Researcher_Synergy",
        "persona":    "06_Persona_Guardian",
        "seo":        "04_SEO_Optimizer",
        "critic":     "05_Critic_Editor_In_Chief",
    }
    SEVERITY_COUNT = {"critical": 5, "high": 3, "medium": 1}

    block_m = re.search(r'LESSONS_START\s*(.*?)\s*LESSONS_END', critic_result, re.S | re.I)
    if not block_m:
        return []

    block = block_m.group(1).strip()
    if not block or block.lower() in ["없음", "none", "-"]:
        return []

    entries = re.split(r'\n\s*---\s*\n', block)
    results = []
    for entry in entries:
        agent_m     = re.search(r'\[AGENT\]:\s*(\w+)', entry, re.I)
        issue_m     = re.search(r'\[ISSUE\]:\s*(.+?)(?=\[|$)', entry, re.I | re.S)
        root_m      = re.search(r'\[ROOT_CAUSE\]:\s*(.+?)(?=\[|$)', entry, re.I | re.S)
        fix_m       = re.search(r'\[FIX\]:\s*(.+?)(?=\[|$)', entry, re.I | re.S)
        severity_m  = re.search(r'\[SEVERITY\]:\s*(\w+)', entry, re.I)

        if not agent_m or not issue_m:
            continue

        agent_key = AGENT_FILE_MAP.get(agent_m.group(1).lower(), "03_Writer_Gardener")
        issue     = issue_m.group(1).strip()
        root      = root_m.group(1).strip() if root_m else ""
        fix       = fix_m.group(1).strip() if fix_m else ""
        severity  = severity_m.group(1).lower() if severity_m else "medium"
        count     = SEVERITY_COUNT.get(severity, 1)

        lesson_text = f"[Critic교사] {issue}"
        if root:  lesson_text += f" | 원인: {root}"
        if fix:   lesson_text += f" | 수정: {fix}"

        results.append({
            "agent_key": agent_key,
            "lesson":    lesson_text[:400],
            "issue":     issue,
            "root_cause": root,
            "fix":       fix,
            "severity":  severity,
            "count":     count,
        })

    logging.info(f"  🎓 Critic 구조화 레슨 파싱: {len(results)}개")
    return results


def imprint_critic_feedback(topic, critic_result, attempt_num):
    logging.info(f"  📚 Critic 피드백 각인... (시도 #{attempt_num})")
    AGENT_FILE_MAP = {
        "Writer":     "03_Writer_Gardener",
        "Researcher": "02_Researcher_Synergy",
        "Persona":    "06_Persona_Guardian",
        "SEO":        "04_SEO_Optimizer",
        "Critic":     "05_Critic_Editor_In_Chief",
    }
    
    # ── [개선] 크리틱 채점 결과에서 세부 성적표 파싱 및 요약 추출
    total_score = "N/A"
    score_match = re.search(r'종합\s*점수:\s*([\d.]+)/10', critic_result)
    if not score_match:
        score_match = re.search(r'SCORE:\s*([\d.]+)', critic_result)
    if score_match:
        total_score = score_match.group(1)
        
    tech = re.search(r'기술적\s*완성도:\s*([\d.]+)/10', critic_result)
    ai_pat = re.search(r'AI\s*패턴\s*제거:\s*([\d.]+)/10', critic_result)
    quality = re.search(r'콘텐츠\s*품질:\s*([\d.]+)/10', critic_result)
    adsense = re.search(r'애드센스\s*승인\s*가능성:\s*([\d.]+)/10', critic_result)
    human = re.search(r'사람\s*블로그\s*느낌:\s*([\d.]+)/10', critic_result)
    
    tech_val = tech.group(1) if tech else "?"
    ai_val = ai_pat.group(1) if ai_pat else "?"
    qual_val = quality.group(1) if quality else "?"
    ads_val = adsense.group(1) if adsense else "?"
    hum_val = human.group(1) if human else "?"
    
    score_summary = f"[점수: {total_score}/10 | 기술: {tech_val}, AI패턴: {ai_val}, 품질: {qual_val}, 애드센스: {ads_val}, 인간느낌: {hum_val}]"
    
    lessons   = load_lessons()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    today     = datetime.now().strftime("%Y-%m-%d")
    updated   = []

    # ── v8.0: 구조화 레슨 우선 파싱 (LESSONS_START...LESSONS_END) ─────────
    structured_lessons = _parse_critic_lessons(critic_result)

    if structured_lessons:
        for sl in structured_lessons:
            file_key = sl["agent_key"]
            if file_key not in lessons: lessons[file_key] = []
            full_lesson = sl["lesson"]
            merged = False
            for existing in lessons[file_key]:
                if _lesson_similarity(full_lesson, existing.get("lesson", "")) >= 0.60:
                    existing["count"] = existing.get("count", 1) + sl["count"]
                    existing["date"]  = timestamp
                    existing["topic"] = topic[:40]
                    logging.info(f"  🔁 [{file_key}] 유사 구조화레슨 count={existing['count']}")
                    merged = True
                    break
            if not merged:
                lessons[file_key].append({
                    "date":       timestamp,
                    "topic":      topic[:40],
                    "attempt":    attempt_num,
                    "lesson":     full_lesson,
                    "issue":      sl.get("issue", ""),
                    "root_cause": sl.get("root_cause", ""),
                    "fix":        sl.get("fix", ""),
                    "severity":   sl.get("severity", "medium"),
                    "count":      sl["count"],
                    "first_seen": today,
                    "source":     "critic_structured",
                })
                logging.info(f"  🎓 [{file_key}] 새 구조화레슨(severity={sl['severity']}): {full_lesson[:80]}")
            lessons[file_key] = lessons[file_key][-30:]
            if file_key not in updated: updated.append(file_key)

    else:
        # ── fallback: 기존 방식 (비구조화 — LESSONS 블록 없는 구버전 Critic 대응) ──
        structured = ask_ai(
            f"다음 반려 사유를 에이전트별로 분류해서 JSON으로 반환하라.\n반려 사유:\n{critic_result}\n\n"
            f'출력 형식 (JSON): {{"Writer": "핵심 개선 지시", "Researcher": "리서치 개선 지시"}}\n'
            f"JSON만 출력. 설명 없음.",
            "JSON만 출력하는 AI 분류기입니다.", LIGHT_MODEL, timeout=60
        )
        try:
            match = re.search(r'\{.*\}', structured, re.DOTALL)
            lessons_parsed = json.loads(match.group()) if match else {"Writer": critic_result[:300]}
        except:
            lessons_parsed = {"Writer": critic_result[:300]}

        for agent_key, lesson_text in lessons_parsed.items():
            if not lesson_text or str(lesson_text).lower() in ["null","none",""]: continue
            file_key = AGENT_FILE_MAP.get(agent_key, agent_key)
            if file_key not in lessons: lessons[file_key] = []
            full_lesson = f"{score_summary} {str(lesson_text).strip()}"
            merged = False
            for existing in lessons[file_key]:
                if _lesson_similarity(full_lesson, existing.get("lesson", "")) >= 0.60:
                    existing["count"] = existing.get("count", 1) + 1
                    existing["date"]  = timestamp
                    existing["topic"] = topic[:40]
                    merged = True
                    break
            if not merged:
                lessons[file_key].append({
                    "date": timestamp, "topic": topic[:40],
                    "attempt": attempt_num, "lesson": full_lesson[:300],
                    "count": 1, "first_seen": today,
                })
            lessons[file_key] = lessons[file_key][-20:]
            updated.append(agent_key)

    save_lessons(lessons)
    promote_to_core_lessons(lessons)  # count >= 3 → core_lessons.json 승격
    logging.info(f"  ✅ 레슨 각인 완료: {updated}")


def imprint_success_feedback(topic, score, word_count, archetype_name, topic_type, critic_result=""):
    """발행 성공 사례를 에이전트별 good_lessons에 각인."""
    logging.info(f"  🌟 성공 사례 각인 ({score:.1%}, {word_count}단어)")
    timestamp = datetime.now().strftime("%Y-%m-%d")
    lessons   = load_lessons()

    # 성공 패턴 요약 (Claude 없이 규칙 기반)
    patterns = []
    if score >= 0.90: patterns.append(f"score {score:.0%}: 아키타입 '{archetype_name}' + 주제타입 '{topic_type}' 조합 최고 성적")
    if word_count >= 2000: patterns.append(f"{word_count}단어 이상 심층 작성이 Critic 승인에 유리")
    if topic_type.startswith("longtail"): patterns.append(f"롱테일 타입 '{topic_type}'은 구체적 증상/실수 묘사가 핵심")
    patterns.append(f"topic='{topic[:40]}' → archetype='{archetype_name}' 조합 승인됨")
    success_lesson = " | ".join(patterns) if patterns else f"정상 승인: {archetype_name}/{topic_type} ({score:.0%})"

    # Writer, Researcher, SEO, Critic 모두에 성공 각인
    for file_key in ["03_Writer_Gardener", "02_Researcher_Synergy", "04_SEO_Optimizer", "05_Critic_Editor_In_Chief"]:
        lessons.setdefault(file_key, [])
        # good_lessons 별도 키로 관리
        good_key = f"{file_key}_good"
        lessons.setdefault(good_key, [])
        lessons[good_key].append({
            "date": timestamp, "topic": topic[:40],
            "score": round(score, 3), "lesson": success_lesson[:300]
        })
        lessons[good_key] = lessons[good_key][-15:]  # 최근 15개 유지

    save_lessons(lessons)
    logging.info(f"  ✅ 성공 각인 완료: {success_lesson[:80]}")

def fetch_ga4_article_lessons():
    """GA4 실제 트래픽/참여율을 에이전트 레슨으로 피드백 (7일 이상 된 미평가 아티클 대상)."""
    try:
        import pickle
        from urllib.parse import urlparse
        from google.auth.transport.requests import Request
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension, OrderBy

        token_path = BASE_DIR / "morning_report_token.pickle"
        if not token_path.exists():
            logging.info("  [GA4 Lesson] 토큰 없음 — 건너뜀 (morning_report 인증 먼저 필요)")
            return

        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        client = BetaAnalyticsDataClient(credentials=creds)

        # 7일 이상 된 미평가 아티클 추출
        db = load_links_db()
        now = datetime.now()
        to_evaluate = []
        for entry in db:
            if entry.get("ga4_evaluated"):
                continue
            pub_str = entry.get("date", "")
            if not pub_str:
                continue
            try:
                age_days = (now - datetime.strptime(pub_str[:10], "%Y-%m-%d")).days
                if age_days >= 7:
                    to_evaluate.append((entry, age_days))
            except:
                continue

        if not to_evaluate:
            logging.info("  [GA4 Lesson] 평가할 아티클 없음")
            return

        logging.info(f"  [GA4 Lesson] {len(to_evaluate)}개 아티클 GA4 평가 시작")

        # GA4: 최근 30일 페이지별 성과 조회
        ga4_resp = client.run_report(RunReportRequest(
            property=f"properties/527664358",
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="pagePath")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration"),
            ],
            limit=500,
        ))
        ga4_data = {}
        for row in ga4_resp.rows:
            path = row.dimension_values[0].value
            mv = row.metric_values
            if len(mv) < 3:
                continue
            ga4_data[path] = {
                "sessions":   int(mv[0].value),
                "engagement": float(mv[1].value),
                "duration":   float(mv[2].value),
            }

        lessons   = load_lessons()
        timestamp = datetime.now().strftime("%Y-%m-%d")
        db_dirty  = False

        for entry, age_days in to_evaluate:
            url   = entry.get("url", "")
            topic = entry.get("topic") or entry.get("title", "unknown")
            try:
                path = urlparse(url).path
            except:
                path = url

            perf       = ga4_data.get(path, {})
            sessions   = perf.get("sessions", 0)
            engagement = perf.get("engagement", 0.0)
            duration   = perf.get("duration", 0.0)

            lesson_text = None
            lesson_type = None

            if sessions >= 20 and engagement >= 0.5:
                lesson_text = (f"[GA4 {age_days}일] sessions={sessions}, "
                               f"engagement={engagement:.0%}, duration={duration:.0f}s "
                               f"| 이 스타일/주제 트래픽 성공 → topic='{topic[:30]}'")
                lesson_type = "good"
            elif sessions < 5 and age_days >= 14:
                lesson_text = (f"[GA4 {age_days}일] sessions={sessions}, "
                               f"engagement={engagement:.0%} "
                               f"| 트래픽 부진 → 이 주제/접근법 재검토 필요: '{topic[:30]}'")
                lesson_type = "bad"

            if lesson_text:
                for file_key in ["03_Writer_Gardener", "04_SEO_Optimizer"]:
                    if lesson_type == "good":
                        good_key = f"{file_key}_good"
                        lessons.setdefault(good_key, [])
                        lessons[good_key].append({
                            "date": timestamp, "topic": topic[:40],
                            "score": round(engagement, 3), "lesson": lesson_text[:300],
                        })
                        lessons[good_key] = lessons[good_key][-15:]
                    else:
                        lessons.setdefault(file_key, [])
                        merged = False
                        for existing in lessons[file_key]:
                            if _lesson_similarity(lesson_text, existing.get("lesson", "")) >= 0.60:
                                existing["count"] = existing.get("count", 1) + 1
                                merged = True
                                break
                        if not merged:
                            lessons[file_key].append({
                                "date": timestamp, "topic": topic[:40],
                                "lesson": lesson_text[:300], "count": 1,
                                "first_seen": timestamp,
                            })
                        lessons[file_key] = lessons[file_key][-20:]

                logging.info(f"  📊 [GA4 Lesson] {topic[:30]}: {lesson_type} | sessions={sessions}, engagement={engagement:.0%}")

            entry["ga4_evaluated"] = True
            db_dirty = True

        save_lessons(lessons)
        promote_to_core_lessons(lessons)
        if db_dirty:
            save_links_db(db)
        logging.info("  ✅ GA4 레슨 피드백 완료")

    except Exception as e:
        logging.warning(f"  [GA4 Lesson] 오류: {e}")


def load_pending():
    if PENDING_APPROVAL.exists():
        try: return json.loads(PENDING_APPROVAL.read_text(encoding='utf-8'))
        except: return []
    return []

# 전역 타임아웃 카운터 (하드웨어 보호용)
consecutive_timeouts = 0

def run_llm(prompt, model=HEAVY_MODEL, system_prompt="", temperature=0.7):
    global consecutive_timeouts
    try:
        # [v5.6] Ollama API 호출
        url = OLLAMA_URL
        payload = {
            "model": model,
            "prompt": f"{system_prompt}\n\nUser: {prompt}\n\nAssistant:",
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 4096, "repeat_penalty": 1.2, "repeat_last_n": 64}
        }
        response = requests.post(url, json=payload, timeout=360)
        response.raise_for_status()
        consecutive_timeouts = 0 # 성공 시 초기화
        return response.json().get("response", "").strip()
    except Exception as e:
        if "timeout" in str(e).lower():
            consecutive_timeouts += 1
            logging.error(f"  🚨 AI 타임아웃 (연속 {consecutive_timeouts}회): {e}")
            if consecutive_timeouts >= 3:
                logging.critical("  🔥 [HARDWARE SAFETY] 연속 타임아웃 발생! 시스템 과부하 방지를 위해 프로세스를 중단합니다.")
                report_to_discord("System", "🔥 [Critical] 연속 타임아웃으로 인한 하드웨어 보호 중단! PC 상태를 확인하세요.")
                sys.exit(1) # 프로세스 강제 종료
        raise e

def save_pending(data):
    PENDING_APPROVAL.parent.mkdir(exist_ok=True, parents=True)
    PENDING_APPROVAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# ============================================================
# 유틸리티
# ============================================================
def clean_ai_output(text):
    text = text.replace("```html", "").replace("```", "")
    text = re.sub(r'^#{1,3}\s+(.*)$', r'<p><strong>\1</strong></p>', text, flags=re.MULTILINE)
    text = text.replace("##", "").replace("###", "")
    # [v5.9.6] CSS(#f0f7ff) 및 앵커(#sec) 보호를 위해 단독 # 삭제 로직 제거
    text = text.replace("**", "")
    bad_starts = ["Here is", "Sure,", "According to", "Based on", "Section:", "Topic:"]
    lines = text.splitlines()
    if lines:
        for s in bad_starts:
            if lines[0].strip().startswith(s):
                text = "\n".join(lines[1:])
                break
    return text.strip()

def _load_anthropic_key():
    """nutristack/.env 에서 ANTHROPIC_API_KEY 로드."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key and key != "your_key_here":
                    os.environ["ANTHROPIC_API_KEY"] = key
                    return key
    return ""

_api_tokens = {"input": 0, "output": 0}  # 글 1개 처리 중 Claude API 사용량 누적

def _load_minimax_key() -> str:
    if os.environ.get("MINIMAX_API_KEY"):
        return os.environ["MINIMAX_API_KEY"]
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MINIMAX_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    os.environ["MINIMAX_API_KEY"] = key
                    return key
    return ""

def ask_minimax(prompt: str, system_prompt: str = "", model: str = "MiniMax-M2.7",
                max_tokens: int = 8192, max_retries: int = 2) -> str:
    """MiniMax API 호출 — Writer/Critic(M2.7) + PPV(M3) 전용."""
    key = _load_minimax_key()
    if not key:
        logging.warning("  [MiniMax] API 키 없음 → 로컬 폴백")
        return ask_ai(prompt, system_prompt, HEAVY_MODEL)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    for attempt in range(max_retries):
        try:
            r = requests.post(
                MINIMAX_API_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens},
                timeout=180,
            )
            if not r.ok:
                logging.warning(f"  [MiniMax] {r.status_code}: {r.text[:100]}")
                time.sleep(2)
                continue
            raw = r.json()["choices"][0]["message"]["content"]
            # <think> 태그 제거 (M2.7/M3 추론 과정)
            import re as _re
            text = _re.sub(r'<think>.*?</think>', '', raw, flags=_re.DOTALL).strip()
            text = clean_ai_output(text)
            if len(text) > 80:
                return text
        except Exception as e:
            logging.error(f"  [MiniMax 오류] (시도{attempt+1}): {e}")
            time.sleep(2)
    logging.warning("  [MiniMax] 실패 → 로컬 폴백")
    return ask_ai(prompt, system_prompt, HEAVY_MODEL)

def ask_claude(prompt, system_prompt="", model="claude-haiku-4-5-20251001", max_tokens=8192):
    """Claude API → MiniMax M3로 대체 (PPV + 3회반려 수정 전용)."""
    return ask_minimax(prompt, system_prompt, MODEL_MINIMAX_PPV, max_tokens=max_tokens)

def ask_ai(prompt, system_prompt, model=HEAVY_MODEL, max_retries=2, timeout=360):
    # MiniMax 모델이면 자동으로 API 라우팅
    if isinstance(model, str) and model.startswith("MiniMax"):
        return ask_minimax(prompt, system_prompt, model)
    clean_instruction = (
        f"{prompt}\n\nSTRICT: Output ONLY the requested content. "
        "No instructions. No markdown. No preamble. Start immediately."
    )
    for attempt in range(max_retries):
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": model, "prompt": clean_instruction, "system": system_prompt,
                "stream": False, "keep_alive": "1m",
                "options": {"temperature": 0.4, "top_p": 0.9, "repeat_penalty": 1.2, "repeat_last_n": 64, "num_predict": 8192}
            }, timeout=timeout)
            text = r.json().get('response','').strip()
            bad  = ["Write ", "Topic:", "Instruction", "CRITICAL", "YOU MUST", "🚨", "🚫", "POST SKELETON"]
            lines = [l for l in text.splitlines() if not any(b in l for b in bad)]
            text  = "\n".join(lines).strip()
            text  = clean_ai_output(text)
            if len(text) > 80: return text
        except Exception as e:
            logging.error(f"AI 오류 (시도{attempt+1}): {e}")
            time.sleep(2)
    return ""

def get_pmids(topic, count=5):
    try:
        from pubmed_fetcher import fetch_relevant_pmids
        papers = fetch_relevant_pmids(topic, count=count)
        # PMID 검증: API로 실제 존재 확인한 것만 사용 (숫자 범위 체크 불필요)
        pmids  = [str(p["pmid"]) for p in papers if str(p["pmid"]).isdigit() and len(str(p["pmid"])) >= 7]
        if pmids:
            logging.info(f"  🔬 PubMed 실제 논문 {len(pmids)}개 검증 완료")
            return pmids
    except Exception as e:
        logging.warning(f"  PubMed 실패 → 폴백: {e}")
    
    t = topic.lower()
    for key, pool_pmids in PMID_DB.items():
        if key in t:
            # 검증된 숫자만 추출
            valid_pool = [str(p) for p in pool_pmids if str(p).isdigit() and len(str(p)) >= 7]
            if not valid_pool: continue
            return random.sample(valid_pool, min(count, len(valid_pool)))
    
    # 기본 폴백에서도 숫자 검증
    default_pool = [str(p) for p in PMID_DB.get("default", []) if str(p).isdigit() and len(str(p)) >= 7]
    return random.sample(default_pool, min(count, len(default_pool)))

def get_labels(topic):
    try:
        # SEO 전전 에이전트 소환 (강화학습 레슨 주입)
        seo_sys = load_agent_with_lessons("04_SEO_Optimizer.md")
        result = ask_ai(
            f"Generate exactly 8 SEO hashtag labels for this supplement blog post topic: {topic}\n"
            f"Rules:\n- Single words only, CamelCase\n- Must include: NutriStackLab, NordicHealth\n"
            f"- Output: comma-separated only.\nExample: Magnesium,BrainHealth,NordicHealth,NutriStackLab",
            seo_sys, MODEL_LABEL_EXTRACT
        )
        labels = [l.strip() for l in result.split(",") if l.strip() and len(l.strip()) < 30][:10]
        if len(labels) >= 3:
            logging.info(f"  🏷️ AI 라벨: {labels}")
            return labels
    except Exception as e:
        logging.warning(f"  라벨 오류: {e}")
    return LABEL_DB["default"]


def get_search_keywords(topic_label: str) -> list:
    """Google Autocomplete로 실시간 검색 키워드 수집 (API key 불필요)"""
    queries = [
        f"{topic_label} supplement",
        f"{topic_label} benefits",
        f"{topic_label} dosage",
    ]
    suggestions = []
    try:
        for q in queries:
            r = requests.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "chrome", "q": q, "hl": "en"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                hits = data[1] if isinstance(data, list) and len(data) > 1 else []
                suggestions.extend(hits[:4])
            time.sleep(0.2)
        # 중복 제거, 최대 10개
        seen, out = set(), []
        for s in suggestions:
            key = s.lower().strip()
            if key not in seen:
                seen.add(key)
                out.append(s)
            if len(out) >= 10:
                break
        return out
    except Exception as e:
        logging.debug(f"  [search_kw] autocomplete failed: {e}")
        return []


def clean_banned(text):
    # [v5.9.9.4] 아포스트로피 정규화 강화
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    
    # [v5.9.7] 문장 시작에서만 어색하게 치환되는 것을 방지해야 하는 필러어 목록
    filler_words = ["surprisingly", "honestly", "oddly enough", "interestingly enough", "anecdotally", "essentially"]
    
    for b, r in BANNED_PHRASES.items():
        # [v5.9.1] 아포스트로피(' vs ’) 유연 매칭 처리
        pattern_str = re.escape(b).replace(r"\'", r"['’]")
        
        # [v5.9.7] 필러어는 문장 시작 또는 구두점 뒤에서만 치환
        if b.lower() in filler_words:
            pattern = re.compile(r'(?i)(^|[.!?]\s+)' + pattern_str)
            def filler_replace(m):
                prefix = m.group(1)
                replacement = r[0].upper() + r[1:] if prefix and len(r) > 0 else r
                return prefix + replacement
            text = pattern.sub(filler_replace, text)
        else:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            def replace_match(m):
                original = m.group(0)
                if original[0].isupper():
                    return r[0].upper() + r[1:] if len(r) > 0 else r
                return r
            text = pattern.sub(replace_match, text)
    return text

def clean_markdown(text):
    # [v5.9.9.3] <p>. 문단 오류 패턴 제거
    text = text.replace("<p>.", "<p>")
    text = re.sub(r'```[\w-]*\n?','',text)
    text = re.sub(r'```','',text)
    text = re.sub(r'^#{1,6}\s*.*$','',text,flags=re.MULTILINE)
    # [v5.9.3] CSS 컬러(#fff), TOC(#sec), 엔티티(&#)를 제외한 나머지 # 기호 삭제 (공백 뒤 #e67e22 대응)
    text = re.sub(r'(?<![="&#: ])#+', '', text)
    text = re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',text)
    text = re.sub(r'\*(.+?)\*',r'\1',text)
    text = re.sub(r'_{1,2}(.+?)_{1,2}',r'\1',text)
    text = re.sub(r'`[^`]*`','',text)
    text = re.sub(r'^\*\s+',r'<li>',text,flags=re.MULTILINE)
    text = re.sub(r'^-\s+',r'<li>',text,flags=re.MULTILINE)
    text = re.sub(r'^---+$','',text,flags=re.MULTILINE)
    text = text.replace('→','&#8594;').replace('->','&#8594;')
    return text.strip()

def clean_html(html):
    pats = [r'🚨.*?(\n|$)',r'🚫.*?(\n|$)',r'YOU MUST.*?(\n|$)',
            r'ZERO TOLERANCE.*?(\n|$)',r'POST SKELETON.*?(\n|$)',
            r'\[Disclosure\].*?(\n|$)',r'Please note:.*?(\n|$)',r'Explanation:.*?(\n|$)']
    for p in pats:
        html = re.sub(p,'',html,flags=re.IGNORECASE)
    html = re.sub(r'<a href="[^"]*"[^>]*></a>','',html)
    html = re.sub(r'https://image\.pollinations\.ai/[^\s"\']+',
                  '[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]',html)
    # AI가 생성한 Unsplash/Pexels 등 불안정 외부 이미지 URL → placeholder (SD→Imgur 파이프라인이 교체)
    html = re.sub(r'https?://(?:images\.unsplash\.com|unsplash\.com|images\.pexels\.com|pexels\.com)/[^\s"\']+',
                  '[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]', html)
    html = re.sub(r'src=""','src="[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]"',html)
    html = clean_markdown(html)
    html = clean_banned(html)
    html = re.sub(r'\n{3,}','\n\n',html)
    return html.strip()

# ============================================================
# Google API
# ============================================================
def get_creds():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE,'rb') as f: creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logging.warning(f"토큰 갱신 실패: {e}")
                if TOKEN_FILE.exists(): TOKEN_FILE.unlink()
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE,'wb') as f: pickle.dump(creds,f)
    return creds

def get_blogger_service():
    try: return build('blogger','v3',credentials=get_creds())
    except Exception as e: logging.error(f"Blogger 오류: {e}"); return None

def upload_to_drive(img_path, filename):
    try:
        svc   = build('drive','v3',credentials=get_creds())
        meta  = {'name': filename}
        media = MediaFileUpload(str(img_path), mimetype='image/png')
        f     = svc.files().create(body=meta,media_body=media,fields='id').execute()
        fid   = f.get('id')
        svc.permissions().create(fileId=fid,body={'type':'anyone','role':'reader'}).execute()
        url = f"https://drive.google.com/thumbnail?id={fid}&sz=s1000"
        logging.info(f"    ✅ Drive 업로드 성공")
        return url
    except Exception as e:
        logging.warning(f"    Drive 실패: {e}")
        return None

# ============================================================
# 이미지 시스템
# ============================================================
def _create_fallback_png(path):
    minimal = bytes([0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,
                     0x49,0x48,0x44,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,
                     0x08,0x02,0x00,0x00,0x00,0x90,0x77,0x53,0xDE,0x00,0x00,0x00,
                     0x0C,0x49,0x44,0x41,0x54,0x08,0xD7,0x63,0xF8,0xFF,0xFF,0x3F,
                     0x00,0x05,0xFE,0x02,0xFE,0xDC,0xCC,0x59,0xE7,0x00,0x00,0x00,
                     0x00,0x49,0x45,0x4E,0x44,0xAE,0x42,0x60,0x82])
    with open(path,'wb') as f: f.write(minimal)

def upload_to_imgur(img_path):
    try:
        with open(img_path,'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        r = requests.post("https://api.imgur.com/3/image",
            headers={"Authorization":"Client-ID 546c25a59c58ad7"},
            data={"image":b64,"type":"base64"}, timeout=30)
        if r.status_code == 200:
            url = r.json()['data']['link']
            logging.info(f"    ✅ Imgur 업로드 성공")
            return url
    except Exception as e:
        logging.warning(f"    Imgur 실패: {e}")
    return None

def img_to_base64(img_path):
    try:
        with open(img_path,'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        return f"data:image/png;base64,{b64}"
    except: return None

# [v6.6] 라이프스타일 이미지 — 음식/보충제/일상 맥락 기반 정적 폴백 DB
IMAGE_STYLE_DB = {
    "magnesium":    "magnesium supplement capsules beside a glass of water and a handful of almonds on a wooden breakfast table",
    "vitamin d":    "vitamin D supplement bottle next to eggs and a sunny window, morning kitchen counter",
    "vitamin d3":   "vitamin D3 softgel capsule beside a plate of salmon and leafy greens, natural light",
    "vitamin k":    "vitamin K supplement beside leafy greens, eggs, and a small notebook on a kitchen counter",
    "omega":        "omega-3 fish oil capsules beside sardines on toast and a glass of water, morning light",
    "omega-3":      "fish oil supplement capsule next to a can of sardines and walnuts, casual kitchen table",
    "zinc":         "zinc supplement tablet beside pumpkin seeds and a light snack on a wooden tray",
    "l-theanine":   "L-theanine capsule beside a cup of green tea and a book, calm morning desk scene",
    "theanine":     "theanine supplement beside a warm mug of tea and a journal on a quiet desk",
    "creatine":     "creatine powder scoop beside a shaker bottle and a banana on a gym bag",
    "lion":         "lion's mane mushroom supplement beside a cup of coffee and morning notes, desk lifestyle",
    "bacopa":       "bacopa supplement bottle beside a glass of water and study notes on a wooden desk",
    "collagen":     "collagen powder beside a bowl of yogurt and berries on a kitchen counter, morning routine",
    "vitamin c":    "vitamin C capsule beside a sliced orange and a glass of water, bright kitchen morning",
    "quercetin":    "quercetin supplement beside apple slices and a handful of berries on a breakfast plate",
    "coq10":        "CoQ10 softgel beside a small piece of fatty fish and a glass of water, lunch setting",
    "nmn":          "NMN supplement bottle beside a glass of water and a weekly pill organizer, morning routine",
    "resveratrol":  "resveratrol capsule beside a bowl of dark berries and a light breakfast, kitchen counter",
    "berberine":    "berberine supplement beside a plate of vegetables and rice, simple healthy meal",
    "probiotics":   "probiotic capsule beside a bowl of greek yogurt and granola on a kitchen table",
    "glutathione":  "glutathione supplement bottle beside a cup of green tea and avocado toast, morning kitchen",
    "ashwagandha":  "ashwagandha capsule beside a mug of warm milk and a journal on a calm evening desk",
    "rhodiola":     "rhodiola supplement beside a cup of black coffee and a morning planner, desk scene",
    "glucosamine":  "glucosamine supplement beside a bowl of bone broth and leafy greens, kitchen table",
    "boron":        "boron supplement beside a small plate of nuts and prunes, simple breakfast setting",
    "pqq":          "PQQ supplement beside a cup of dark coffee and a handful of kiwi fruit, morning counter",
    "melatonin":    "melatonin supplement beside a glass of water and a dim bedside lamp, nighttime bedroom",
    "glycine":      "glycine powder beside a mug of warm tea and a journal on a calm desk at night",
    "kefir":        "kefir glass beside omega-3 capsules and fresh berries on a morning kitchen counter",
    "default":      "supplement bottle beside a glass of water and a light healthy snack on a wooden kitchen counter",
}

# [v6.6] 섹션별 구도 — 라이프스타일 촬영 스타일
SECTION_COMPOSITIONS = [
    "flat-lay top-down view on a wooden kitchen counter, soft natural window light",
    "45-degree angle shot on a marble countertop, warm morning sunlight, shallow depth of field",
    "close-up with bokeh background, hand holding supplement capsule, natural kitchen setting",
    "lifestyle scene, supplement bottle open beside a half-eaten breakfast plate, casual",
    "minimalist composition, single supplement capsule beside a glass of water, clean white surface",
    "over-the-shoulder lifestyle shot, person at a kitchen table with supplement and coffee",
    "styled flat-lay with supplement, notebook, and light snack, overhead soft light",
    "relaxed morning scene, supplement beside a cup of tea or coffee on a wooden desk",
]

def get_image_prompt(topic, img_key, title="", hook=""):
    """[v6.6] Claude API로 글 내용 기반 라이프스타일 이미지 프롬프트 생성. 폴백: 정적 DB."""
    is_hero = (img_key == "hero")
    realism_suffix = (
        "realistic lifestyle photography, Canon 5D Mark IV, natural light, warm tones, "
        "sharp focus, high resolution, no text, no watermark, photorealistic, "
        "no people, no person, no human, product and environment only"
    )

    # 1순위: Claude API로 컨텍스트 기반 생성
    try:
        context_lines = [f"Supplement blog topic: {topic}"]
        if title: context_lines.append(f"Article title: {title[:80]}")
        if hook:  context_lines.append(f"Article hook: {hook[:150]}")
        composition_hint = (
            "vertical portrait image (2:3 ratio), Pinterest-style, supplement + food styled on kitchen counter or wooden tray, top third empty for text overlay"
            if is_hero else random.choice(SECTION_COMPOSITIONS)
        )
        ai_prompt = ask_ai(
            "\n".join(context_lines) + "\n\n"
            f"Write a SHORT Stable Diffusion image prompt (max 45 words) for a REALISTIC LIFESTYLE PHOTO "
            f"for this personal health blog post.\n"
            f"Composition: {composition_hint}\n"
            f"RULES:\n"
            f"- Show supplement + food/drink/everyday object in a real home/kitchen setting\n"
            f"- NO molecules, NO diagrams, NO aurora, NO scientific visualization, NO people's faces\n"
            f"- Warm natural light, realistic, grounded\n"
            f"Output ONLY the SD prompt. No explanation. No quotes.",
            "", LIGHT_MODEL, timeout=60
        )
        if ai_prompt and len(ai_prompt.strip()) > 15:
            logging.info(f"    🎨 로컬 이미지 프롬프트 생성 완료")
            return f"{ai_prompt.strip()}, {realism_suffix}"[:280]
    except Exception as e:
        logging.warning(f"    이미지 프롬프트 Claude 실패: {e}")

    # 폴백: 정적 DB 키워드 매칭
    topic_lower = topic.lower()
    style = IMAGE_STYLE_DB["default"]
    for keyword, img_style in IMAGE_STYLE_DB.items():
        if keyword != "default" and keyword in topic_lower:
            style = img_style
            break
    composition = (
        "vertical portrait composition (2:3), Pinterest-style styled shot, supplement and food on wooden tray or kitchen counter, top area clear for text, soft natural light"
        if is_hero else random.choice(SECTION_COMPOSITIONS)
    )
    return f"{style}, {composition}, {realism_suffix}"[:280]


def _sd_health_check():
    """SD API 가용 여부 빠른 확인 (5초)."""
    try:
        requests.get(f"{SD_API_URL}/sdapi/v1/sd-models", timeout=5)
        return True
    except Exception:
        return False

def _sd_generate(prompt, is_hero=True):
    """[v6.6] 라이프스타일 포토리얼리스틱 설정 — 가로형, epicrealismXL 최적화."""
    if not SD_ENABLED: return None
    if not _sd_health_check():
        logging.warning("    SD API 응답 없음 — 폴백으로 즉시 전환")
        return None
    try:
        model  = SD15_MODEL
        steps  = 24 if is_hero else 20
        # 히어로: 2:3 세로형 768×1152 (속도/품질 균형) / 섹션: 768×512 가로형
        width, height = (768, 1152) if is_hero else (768, 512)
        negative_prompt = (
            "person, people, human, man, woman, face, body, hands, skin, portrait, "
            "molecule, diagram, scientific visualization, 3d render, cgi, cartoon, illustration, "
            "painting, aurora, nordic winter glow, neural network, abstract, dark background, "
            "neon, cyberpunk, text, watermark, logo, blurry, low quality, deformed, ugly, "
            "extra limbs, face close-up, oversaturated"
        )
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": steps,
            "width": width,
            "height": height,
            "cfg_scale": 6.5,
            "sampler_name": "DPM++ 2M Karras",
            "override_settings": {"sd_model_checkpoint": model},
        }
        r = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=120)
        r.raise_for_status()
        return base64.b64decode(r.json()["images"][0])
    except Exception as e:
        logging.warning(f"    SD API 실패: {e}")
        return None

def get_image_url(img_desc, img_fn, img_path):
    logging.info(f"  📷 이미지 생성: {img_fn}")
    is_hero   = "hero" in img_fn.lower()
    img_bytes = _sd_generate(img_desc, is_hero=is_hero)
    if img_bytes:
        with open(img_path,'wb') as f: f.write(img_bytes)
        logging.info(f"    ✅ SD 생성 성공 (SD1.5)")
    else:
        width, height = (768, 1152) if is_hero else (896, 512)
        poll_url = (f"https://image.pollinations.ai/prompt/"
                    f"{requests.utils.quote(img_desc[:120])}"
                    f"?width={width}&height={height}&nologo=true")
        local_ok = False
        for _ in range(3):
            try:
                r = requests.get(poll_url, timeout=50)
                if r.status_code == 200 and len(r.content) > 5000:
                    with open(img_path,'wb') as f: f.write(r.content)
                    local_ok = True; break
            except: pass
            time.sleep(3)
        if not local_ok:
            # fallback PNG는 Imgur에 올리지 않음 (503바이트 깨진 이미지 문제)
            # base64 inline으로 직접 반환
            _create_fallback_png(img_path)
            logging.warning(f"    ⚠️ 이미지 생성 실패 → fallback base64 사용 (Imgur 업로드 생략)")
            return img_to_base64(img_path) or "[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]"
    # [v5.6] 구글 드라이브 제거 - 로컬 -> Imgur/Base64 직행
    logging.info(f"    📤 이미지 업로드 중... (Drive Skip)")
    url = upload_to_imgur(img_path)
    if url: return url
    return img_to_base64(img_path) or "[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]"


def build_img_html(url, alt, caption):
    # [v5.9.9.7] Alt 태그 키워드 스터핑 방지 및 서술형 변환
    clean_alt = alt.replace("mistakes", "").replace("common", "").replace("protocol", "").strip()
    # [v5.9.9.9] alt 정제 강화: 불필요한 접두사 제거 (And/and/Or/or)
    clean_alt = re.sub(r'^(and|And|or|Or)\s+', '', clean_alt).strip()
    if len(clean_alt.split()) < 3:
        clean_alt = f"Health supplement routine: {clean_alt}"
    
    return (f'<div style="margin:30px 0; text-align:center;">'
            f'<img src="{url}" alt="{clean_alt}" style="max-width:100%; height:auto; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.1);" />'
            f'<div style="margin-top:10px; font-size:0.9em; color:#666; font-style:italic; '
            f'padding:12px; text-align:center;">{caption}</div></div>')


# ============================================================
# 제목 생성
# ============================================================
def generate_title(topic, archetype_name="science-heavy", topic_type="synergy", archetype_cfg=None):
    if archetype_cfg is None: archetype_cfg = {}
    words     = topic.replace("_"," ").replace("-"," ").strip().split()
    
    # [v6.3] Comprehensive stop words to prevent grammatical/auxiliary/generic words from being extracted as nutrients
    stop_words = {
        "the", "for", "with", "vs", "or", "of", "in", "a", "an", "and", "to", "at", "by", "from", "on", "into", "than", "about",
        "my", "your", "our", "their", "his", "her", "its", "me", "you", "him", "them", "us", "i", "we", "they", "who", "whom", "whose",
        "how", "why", "when", "what", "where", "which", "whether",
        "do", "does", "did", "done", "doing", "is", "am", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having",
        "should", "would", "could", "can", "will", "shall", "must", "may", "might", "ought",
        "nordic", "stack", "guide", "science", "boost", "protocol", "recipe", "symptom", "mistake", "mistakes",
        "stop", "stopped", "stopping", "stops", "start", "started", "starting", "starts", "common", "avoid", "avoiding",
        "wrong", "making", "failing", "effectively", "actually", "timing", "routine", "simple", "taking", "take", "takes", "took",
        "comparing", "compare", "compared", "combining", "combine", "combined", "using", "use", "used", "uses",
        "trying", "try", "tried", "tries", "testing", "test", "tested", "tests", "fail", "failed", "fails",
        "prefer", "preferred", "preferring", "prefers", "over", "under", "between", "each", "other", "another", "cancel", "out",
        "benefit", "benefits", "maximizes", "maximize", "absorption", "evidence", "findings", "clinical", "research", "data",
        "people", "person", "personal", "experience", "work", "worked", "working", "works", "matter", "matters", "minds", "mind",
        "brain", "gut", "axis", "shield", "stress", "smoothie", "bowl", "morning", "evening", "night", "day", "daily", "cozy", "happy",
        "ideal", "optimum", "optimal", "maximizing", "enhancing", "enhance", "enhances", "enhanced",
        "dangerous", "safe", "safety", "long", "term", "short", "dose", "dosage", "amount", "intake", "level", "levels", "risk",
        "signs", "deficiency", "symptoms", "ignoring", "low", "high", "fix", "quickly", "workout", "bed", "huge", "sleepy", "bloating",
        "normal", "weird", "dreams", "upset", "stomach", "anxious", "ruins", "effective", "efficacy", "cost", "choose",
        "mechanism", "mechanisms", "synergy", "synergistic", "combo", "combination", "combinations", "interaction", "interactions",
        "pairing", "pairings", "nutrient", "nutrients", "alternative", "alternatives"
    }
    
    # [v6.2] Smart keyword extraction
    # Single uppercase letters (A,B,C,D,E,K …) are vitamin designations — always keep them
    def _is_valid_keyword(w):
        cw = re.sub(r'[^\w]', '', w)
        is_vitamin_code = len(cw) == 2 and bool(re.match(r'^[A-Za-z]\d$', cw))  # D3, K2, B6 등
        return cw.lower() not in stop_words and (len(cw) > 2 or (len(cw) == 1 and cw.isupper()) or is_vitamin_code)
    key_words_full = [w for w in words if _is_valid_keyword(w)]
    # .title() 사용 금지 — apostrophe 뒤 글자도 대문자화하는 버그 (e.g. "Shouldn'T")
    # 대신 각 단어의 첫 글자만 대문자화
    topic_label = " ".join(w[0].upper() + w[1:] if w else w for w in key_words_full[:2]) if key_words_full else "Supplement"

    bad_labels = ["Stopped", "Stop", "Taking", "Take", "Started", "Using", "Use", "Found", "Actually", "Truth", "Comparing", "Combining", "Trying", "Testing", "Avoid"]
    for bl in bad_labels:
        if bl in topic_label: topic_label = topic_label.replace(bl, "").strip()
    if "Zinc" in topic.title(): topic_label = "Zinc"
    # .title()이 대소문자 혼합 영양소명을 망가뜨리는 경우 복구
    _CASE_FIXES = {"Same": "SAMe", "Coq10": "CoQ10", "Nmn": "NMN", "Pqq": "PQQ",
                   "Hmb": "HMB", "Nad": "NAD", "Epa": "EPA", "Dha": "DHA"}
    for wrong, right in _CASE_FIXES.items():
        if wrong in topic_label: topic_label = topic_label.replace(wrong, right)
    if not topic_label: topic_label = "Supplement"

    key_words = []
    for w in words:
        if _is_valid_keyword(w):
            key_words.append(w.strip(',.:;'))
            
    # [v6.2] Fallback if key_words is empty after filtering
    if not key_words:
        key_words = [w.strip(',.:;') for w in words if _is_valid_keyword(w)]
        filtered = [w for w in key_words if re.sub(r'[^\w]', '', w.lower()) not in stop_words]
        if filtered:
            key_words = filtered
        else:
            key_words = ["Supplement", "Alternative"]
    
    arch_styles = {
        "minimalist":       f"Why I Started Taking {topic_label}",
        "quick-answer":     f"How Much {topic_label} Do You Actually Need?",
        "listicle":         f"5 Things That Happened When I Tried {topic_label}",
        "journal-tone":     f"My Experience With {topic_label}: What Worked",
        "nordic-anecdotal": f"Why I Started Pairing {topic_label} With My Supplement Routine",
        "research-note":    f"What the Science Actually Says About {topic_label}",
        "short-practical":  f"How I Actually Take {topic_label} Every Day",
    }
    
    key_words = key_words[:3]
    if not key_words: key_words = [topic[:15].strip()]

    use_nordic = archetype_cfg.get("include_nordic", True)
    power_word = "Nordic" if use_nordic else random.choice(
        ["Practical","Daily","Simple","Modern","Essential"])

    type_styles = {
        "side-effects":       f"{topic_label} Side Effects: What the Data Shows",
        "antagonism":         f"Why You Shouldn't Combine {' and '.join(key_words[:2])}",
        "food-combo":         f"Best Foods to Combine With {topic_label}",
        "deficiency":         f"Common Signs of {topic_label} Deficiency",
        "timing":             f"When to Take {topic_label}: A {power_word} Timing Guide",
        "recipe":             f"The {topic_label} Protocol: A {power_word} Recipe",
        "comparison":         f"{key_words[0]} vs {key_words[1] if len(key_words) >= 2 else 'Alternative'}: Which Is Better?",
        # [v6.0] 완전 가이드 전용 제목
        "comprehensive_guide": random.choice(TITLE_STYLES_GUIDE).format(nutrient=topic_label),
    } if key_words else {}

    if topic_type in type_styles:       base_title = type_styles[topic_type]
    elif archetype_name in arch_styles: base_title = arch_styles[archetype_name]
    else:                               base_title = None

    # [v6.4] 실시간 구글 검색어로 제목 키워드 강화
    search_kws = get_search_keywords(topic_label)
    search_hint = ""
    if search_kws:
        search_hint = "Real Google searches for this topic:\n" + "\n".join(f"  - {s}" for s in search_kws[:8]) + "\n"
        logging.info(f"  [search_kw] {len(search_kws)}개 수집: {search_kws[:3]}")

    prompt = (
        f"Task: Write ONE blog post title that ranks on Google AND feels like a real person wrote it.\n"
        f"Topic: {topic}\nArticle style: {archetype_name}\n"
        f"Key nutrients: {', '.join(key_words)}\n"
        + (f"Base title idea: {base_title}\n" if base_title else "")
        + search_hint
        + f"Requirements:\n"
        f"- Max 65 chars. No quotes. No numbering. No 'Title:' prefix.\n"
        f"- FORMULA: [Nutrient] [searchable aspect]: [personal hook]\n"
        f"  Good examples:\n"
        f"  'Magnesium Glycinate Dosage: The Form That Finally Worked for Me'\n"
        f"  'Vitamin D3 Deficiency: Why I Got It Wrong for Two Years'\n"
        f"  'NMN Timing: The Mistake That Delayed My Results'\n"
        f"  'Iron Absorption: How I Finally Fixed My Energy Levels'\n"
        f"- The [searchable aspect] MUST be one of: Dosage, Benefits, Side Effects, Timing, Absorption, Deficiency, vs, Types, Guide, Results\n"
        f"- Must include the main nutrient name\n"
        f"- NO 'Is X Worth Taking', NO 'What the Research Says', NO 'Complete Guide' alone\n"
        f"Output: ONLY the title text. One line."
    )
    # SEO 전문 에이전트 소환 (강화학습 레슨 주입)
    seo_sys = load_agent_with_lessons("04_SEO_Optimizer.md")
    raw   = ask_ai(prompt, seo_sys, MODEL_TITLE_FAQ).strip()
    
    # ★ 제목 버그 패치: AI 서술어 및 접두사 제거
    clean_title = raw.split("\n")[0].strip()
    clean_title = re.sub(r'^(Title|제목|Proposed Title|Title Idea)[:\s]+', '', clean_title, flags=re.IGNORECASE)
    clean_title = clean_title.strip('"* ')
    
    first = clean_title
    bad = ["here are","options","task:","requirements:","example","1.","2.","**","title:","format:","output:","proposed"]
    is_bad = (not first or len(first) < 10 or len(first) > 85
              or any(p in first.lower() for p in bad)
              or first.lower().startswith(("the topic","write","task","here")))

    # [v3.5] 이중 검증: 제목이 여전히 오염되었는지 확인
    retry_count = 0
    while retry_count < 3:
        is_still_bad = (len(first.split()) < 3 
                       or ":" in first and len(first.split(":")[0]) < 3
                       or any(p in first.lower() for p in ["best:", "why and", "the and", "is protocol", "taking and"]))
        if not is_still_bad: break
        
        # [v3.7] 주제 타입별 맞춤형 폴백 (논리 루프 방지)
        retry_count += 1
        A = next((w for w in key_words if w.lower() not in stop_words), "Nutrient")
        B = next((w for w in key_words[1:] if w.lower() not in stop_words), "Alternative")

        if topic_type == "comparison":
            first = f"{topic_label} vs {B}: Which Is Better?"
        elif topic_type in ["food-combo", "recipe"]:
            first = f"Best Foods to Take With {topic_label}"
        elif topic_type == "side-effects":
            first = f"{topic_label} Side Effects: What to Expect"
        elif topic_type == "antagonism":
            first = f"Why You Shouldn't Combine {topic_label} and {B}"
        elif topic_type == "timing":
            first = f"When to Take {topic_label}: Morning vs Night"
        elif topic_type == "deficiency":
            first = f"{topic_label} Deficiency: Signs and How to Fix It"
        else:
            _else_fallbacks = [
                f"What I Learned Taking {topic_label} for the First Time",
                f"My First Month on {topic_label}: What Changed and What Didn't",
                f"The {topic_label} Mistake I Kept Making",
                f"Why I Kept Getting {topic_label} Wrong",
                f"I Took {topic_label} Wrong for Months — Here's What Finally Worked",
            ]
            first = random.choice(_else_fallbacks)
        
        logging.warning(f"  ⚠️ 제목 오염 감지 → 주제({topic_type}) 맞춤형 자가 수정 ({retry_count}회)")

    first = first.replace('"','').replace("'","").strip()
    # 문장 첫 글자 대문자 보장
    first = first[0].upper() + first[1:] if first else ""
    
    # [v6.3] 최종 제목 정제: 'Common' 등 불필요한 단어 제거 (최종 필터)
    # NOTE: "guide"는 포괄가이드 제목에서 의도적으로 사용 → 제거 안 함
    # "complete"는 "Is X Complete Worth Taking" 같은 어색한 제목에서 누출되므로 제거
    clean_title = re.sub(r'(?i)\b(common|mistakes|tips|avoid|protocol|mechanism|mechanisms|synergy|combination|combinations|effectively|optimal|optimize|complete)\b\s*', '', first).strip()
    # 'and and' 또는 문장 시작의 'and ' 등 정제
    clean_title = re.sub(r'\b(and|with)\s+(and|with)\b', 'and', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    if clean_title.lower().startswith("and "): clean_title = clean_title[4:]
    if clean_title.lower().endswith(" and"): clean_title = clean_title[:-4]

    # [v5.9.9.9] 'Combine and Zinc' -> 'Taking Zinc' 같은 자연스러운 변환 (옵션)
    clean_title = re.sub(r'(?i)\bcombine\s+and\b', 'Taking', clean_title)

    # 중복 영양소명 제거: 첫 의미 단어가 제목 뒤에서 반복될 때 제거 (e.g., "Probiotics ... Probiotics ...")
    _words = clean_title.split()
    if len(_words) >= 3:
        _first = _words[0]
        if len(_first) > 4 and not _first.lower() in ('what','when','does','will','why','how','should','can','are','have'):
            _rest = ' '.join(_words[1:])
            _rest_cleaned = re.sub(rf'(?i)\s*[:\-]?\s*\b{re.escape(_first)}\b\s*[:\-]?\s*', ' ', _rest).strip()
            if _rest_cleaned != _rest:
                clean_title = re.sub(r'\s+', ' ', _first + ' ' + _rest_cleaned).strip()

    # 연속 콜론/하이픈 정리 (e.g., "Probiotics : : Guide" → "Probiotics: Guide")
    clean_title = re.sub(r'\s*:\s*:\s*', ': ', clean_title)
    clean_title = re.sub(r'\s*:\s*$', '', clean_title).strip()

    # 의문문 제목에 ? 누락 시 자동 추가 (e.g., "Is HMB Worth Taking What the Research Says")
    if re.match(r'^(Is|Are|Does|Do|Can|Should|Will|Has|Have)\s', clean_title, re.I):
        if '?' not in clean_title:
            # "What/How/Why/When/Which" 절 앞에 ? 삽입, 없으면 제목 끝에 추가
            sub_clause = re.search(r'\s+(What|How|Why|When|Which|And)\s', clean_title, re.I)
            if sub_clause:
                pos = sub_clause.start()
                clean_title = clean_title[:pos] + '?' + clean_title[pos:]
            else:
                clean_title += '?'

    # NOTE: 60자 제한은 Blogger API 제목이 아닌 HTML H1 전용 → assemble_post 내에서만 처리

    # [v6.7] entity 강제 보장: 핵심 영양소명이 제목에 없으면 앞에 삽입
    if topic_label and topic_label.lower() not in clean_title.lower():
        clean_title = f"{topic_label}: {clean_title}"

    return clean_title

# ============================================================
# FAQ 스키마
# ============================================================
def build_faq_schema(pairs):
    entities = []
    for q, a in pairs:
        entities.append({
            "@type": "Question", "name": q.replace('"',"'").strip(),
            "acceptedAnswer": {"@type":"Answer","text": a.replace('"',"'").strip()}
        })
    schema = {"@context":"https://schema.org","@type":"FAQPage","mainEntity":entities}
    return (f'<script type="application/ld+json">\n'
            f'{json.dumps(schema,indent=2,ensure_ascii=False)}\n</script>')

def parse_faq(text):
    pairs = []
    lines = text.strip().splitlines()
    cq, ca = None, []
    for line in lines:
        line = line.strip()
        if not line: continue
        if '<h3>' in line or line.lower().startswith('q:') or ('?' in line and len(line)<200):
            if cq and ca: pairs.append((cq,' '.join(ca)))
            cq = re.sub(r'<[^>]+>','',line).replace('Q:','').strip()
            ca = []
        elif '<p>' in line or line.lower().startswith('a:'):
            cl = re.sub(r'<[^>]+>','',line).replace('A:','').strip()
            if cl: ca.append(cl)
        elif cq and line:
            cl = re.sub(r'<[^>]+>','',line).strip()
            if cl: ca.append(cl)
    if cq and ca: pairs.append((cq,' '.join(ca)))
    return pairs[:5]

# ============================================================
# TOC 자동 주입 (comprehensive-guide 전용)
# ============================================================
def _inject_toc(html: str) -> str:
    """TOC가 없을 때 h2 id="secN" 태그로부터 자동 생성해 h1 바로 뒤에 삽입."""
    if 'href="#sec' in html:
        return html  # 이미 TOC 있음
    h2_matches = re.findall(r'<h2[^>]*\bid="sec(\d+)"[^>]*>([^<]+)</h2>', html)
    if len(h2_matches) < 3:
        return html
    toc_items = "".join(f'<li><a href="#sec{idx}">{name.strip()}</a></li>' for idx, name in h2_matches)
    if 'id="faq"' in html:
        toc_items += '<li><a href="#faq">Frequently Asked Questions</a></li>'
    toc_div = (
        '<div style="background:#f9f9f9; border:1px solid #ddd; padding:15px; '
        'margin:20px 0; border-radius:8px;">'
        '<strong style="font-size:1.1em;">Contents</strong>'
        f'<ul style="margin-top:10px; list-style-type:none; padding-left:5px; line-height:1.8;">{toc_items}</ul></div>'
    )
    return re.sub(r'(</h1>)', r'\1\n' + toc_div, html, count=1)

# ============================================================
# HTML 조립 엔진
# ============================================================
def assemble_post(topic, title, hook, sections, images, pmids, faq_text, related_links, archetype_cfg, topic_type, meta_desc=""):
    arch          = archetype_cfg["name"]
    include_faq   = archetype_cfg["include_faq"]
    include_toc   = archetype_cfg["include_toc"]
    include_meth  = archetype_cfg["include_methodology"]
    include_kt    = archetype_cfg["include_kt"]
    include_cliff = archetype_cfg["include_cliff"]
    img_count     = archetype_cfg["image_count"]

    title = re.sub(r'\b(and|And)\s+(and|And)\b', 'and', title, flags=re.IGNORECASE)
    clean_title = re.sub(r'[^\w\s:—\-\(\)]','',title).strip()
    if len(clean_title) > 60: clean_title = clean_title[:57]+"..."

    stop_sec = {"and","the","for","with","vs","or","of","in","a","an","synergy",
                "protocol","guide","science","why","how","stack","system","dual",
                "reset","cycle","without","other","taking","vitamin","after","before",
                "during","should","does","is","actually","more","than","best","better","good","matter","think",
                "bioavailability"}
    topic_words_sec = [w.strip(':,.') for w in topic.split()
                       if w.lower() not in stop_sec and (len(w) > 2 or (len(w) == 1 and w.isupper())
                       or (len(re.sub(r'[^\w]','',w)) == 2 and bool(re.match(r'^[A-Za-z]\d$', re.sub(r'[^\w]','',w)))))]
    topic_label = " and ".join(topic_words_sec[:2]) if len(topic_words_sec) >= 2 else (topic_words_sec[0] if topic_words_sec else topic)
    topic_label = topic_label.strip(': ')
    
    # [v5.9.9.9] topic_label에서도 Common/Mistakes 제거 및 'And ' 접두사 방지
    topic_label = re.sub(r'(?i)\b(common|mistakes|tips|avoid|guide|protocol)\b', '', topic_label).strip()
    topic_label = re.sub(r'(?i)^(and|with)\s+', '', topic_label).strip()
    # .title() 금지 — apostrophe 버그 방지
    topic_label = " ".join(w[0].upper() + w[1:] if w else w for w in topic_label.split())

    disc = ('<p><em>Disclosure: This post may contain affiliate links. '
            'Purchases made through these links support NutriStack Lab '
            'at no additional cost to you.</em></p>')

    hero_url = images.get("hero","[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]")
    # [v5.9.8] 이미지 캡션 및 alt 랜덤화 (Footprint 제거)
    hero_alts = [
        f"my {topic_label} container next to breakfast",
        f"testing {topic_label} during week three",
        f"my {topic_label} bottle on the counter",
        f"my {topic_label} setup this month"
    ]
    hero_caps = [
        f"The tub I almost returned after week two.",
        f"My setup during the first month of testing.",
        f"What my counter looked like during the trial.",
        f"The bottle I kept second-guessing."
    ]
    hero = build_img_html(hero_url, random.choice(hero_alts), random.choice(hero_caps))

    takeaways = ""
    if include_kt:
        kt_raw = ask_ai(
            f"Write exactly 3 short bullet points for a personal blog post about: {topic}\n"
            f"Style: first-person personal observations — what surprised the writer, what changed, what was subtle.\n"
            f"Examples: 'I felt nothing for the first few weeks.' / 'My mood improved before my energy did.' / 'The changes were subtle, not dramatic.' / 'Timing mattered more than I expected.'\n"
            f"Output: 3 plain text lines only. No HTML. No bullets. No mechanism or research explanations.",
            "You are a personal supplement blogger. Write 3 short personal observation lines. Output only the 3 lines.", LIGHT_MODEL
        ).strip()
        kt_lines = [re.sub(r'^\d+[\.\)]\s*', '', l.lstrip('-* ').strip()) for l in kt_raw.splitlines() if l.strip()][:3]
        if len(kt_lines) < 3:
            kt_lines = [
                f"I didn't notice anything for the first couple of weeks.",
                f"The difference showed up gradually, not all at once.",
                f"What changed was subtle — but it was real.",
            ]
        # [v7.0] KT 박스 제목/색상 랜덤화
        kt_title = random.choice(KT_TITLES)
        kt_bg, kt_border = random.choice(KT_THEMES)
        kt_html = "".join([f"<li>{clean_banned(l)}</li>" for l in kt_lines])
        takeaways = (
            f'<div style="background:{kt_bg}; border-left:4px solid {kt_border}; padding:16px; margin:20px 0;">'
            f'<strong>{kt_title}</strong><ul>{kt_html}</ul></div>'
        )

    clean_hook = clean_html(hook)
    # [v7.0] hook 표시 방식 다양화 (4가지)
    _hook_style = random.randint(0, 3)
    if arch in ["journal-tone", "nordic-anecdotal"]:
        hook_block = f'<hr>\n<p><em>{clean_hook}</em></p>\n<hr>'
    elif arch in ["quick-answer", "minimalist"]:
        hook_block = f'<p>{clean_hook}</p>'
    elif _hook_style == 0:
        hook_block = f'<hr>\n<p>{clean_hook}</p>\n<hr>'
    elif _hook_style == 1:
        hook_block = (f'<div style="background:#fffdf0;border-left:3px solid #ccc;padding:14px 18px;margin:20px 0;">'
                      f'<p style="margin:0;font-style:italic;">{clean_hook}</p></div>')
    elif _hook_style == 2:
        hook_block = f'<p><em>{clean_hook}</em></p>'
    else:
        hook_block = (f'<div style="padding:16px 0;border-top:1px solid #eee;border-bottom:1px solid #eee;margin:20px 0;">'
                      f'<p style="margin:0;">{clean_hook}</p></div>')

    toc_html  = ""
    sec_keys  = list(sections.keys())
    if include_toc and len(sec_keys) >= 3:
        # [v7.0] TOC 스타일 랜덤화
        ts = random.choice(TOC_STYLES)
        toc_items = "".join(
            [f'<li><a href="#sec{i}" style="color:{ts["link_color"]};text-decoration:none;">{ts["prefix"]}{s}</a></li>'
             for i, s in enumerate(sec_keys)]
        )
        if include_faq:
            toc_items += f'<li><a href="#faq" style="color:{ts["link_color"]};text-decoration:none;">{ts["prefix"]}Frequently Asked Questions</a></li>'
        toc_html = (
            f'<div style="background:{ts["bg"]}; border:1px solid {ts["border"]}; padding:15px; '
            'margin:20px 0; border-radius:8px;">'
            '<strong style="font-size:1.1em;">Contents</strong>'
            f'<ul style="margin-top:10px; list-style-type:none; padding-left:5px; line-height:1.8;">{toc_items}</ul></div>'
        )


    body = ""
    for i, (sec_name, content) in enumerate(sections.items()):
        clean_content = clean_html(content)
        sec_img = ""
        img_key = f"s{i+1}"
        if images.get(img_key):
            # [v5.6] 랜덤 캡션 적용
            caption = random_caption(sec_name, topic)
            sec_img = build_img_html(images[img_key], f"{topic.lower()} {sec_name.lower()}", caption)

        pmid_block = ""
        # [v7.0] 과학 밀도 랜덤화 — archetype별 density로 어느 섹션에 PMID 배치할지 결정
        if i == 0 and not hasattr(assemble_post, "_pmid_sections_cache"):
            # 섹션 루프 첫 진입 시 1회만 결정 (함수 속성으로 임시 캐시)
            _density = archetype_cfg.get("science_density", "medium")
            _total = len(sections)
            _avail = min(len(pmids), _total)
            if _density == "none" or _avail == 0:
                _pmid_secs = set()
            elif _density == "low":
                _n = random.randint(0, min(1, _avail))
                _pmid_secs = set(random.sample(range(_total), _n)) if _n else set()
            elif _density == "medium":
                _n = random.randint(1, min(2, _avail))
                _pmid_secs = set(random.sample(range(_total), _n))
            else:  # high
                _n = random.randint(2, min(3, _avail))
                _pmid_secs = set(random.sample(range(_total), _n))
            assemble_post._pmid_sections_cache = (_pmid_secs, list(pmids))
        _pmid_secs_use, _pmid_list = getattr(assemble_post, "_pmid_sections_cache", (set(), list(pmids)))

        if i in _pmid_secs_use and _pmid_list:
            pid = _pmid_list[sorted(_pmid_secs_use).index(i) % len(_pmid_list)]
            idx_file = META_DIR / "last_pmid_variation.json"
            last_idx = 0
            if idx_file.exists():
                try: last_idx = int(idx_file.read_text())
                except: last_idx = 0
            pmid_variations = [
                f"Clinical data via PMID {pid} confirms measurable progress in this area.",
                f"According to research (PMID {pid}), these markers showed consistent improvement.",
                f"Data published under PMID {pid} validates the physiological response discussed here.",
                f"As noted in PMID {pid}, researchers observed a significant correlation with these outcomes.",
                f"Further evidence from PMID {pid} supports the timing approach outlined here.",
                f"One study (PMID {pid}) found results that aligned closely with my own experience.",
                f"Research under PMID {pid} revealed patterns that help explain what I noticed.",
            ]
            new_idx = (last_idx + 1) % len(pmid_variations)
            idx_file.write_text(str(new_idx))
            pmid_text = pmid_variations[new_idx]
            # [v7.0] PMID 표시 방식도 3가지로 변형
            _pmid_style = random.randint(0, 2)
            if _pmid_style == 0:
                pmid_block = (f'<blockquote><p>Research published via '
                             f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pid}/" '
                             f'rel="noopener noreferrer">PMID {pid}</a>: {pmid_text}</p></blockquote>')
            elif _pmid_style == 1:
                pmid_block = (f'<p style="font-size:0.95em;color:#555;border-left:3px solid #ddd;padding-left:12px;">'
                             f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pid}/" rel="noopener noreferrer">PMID {pid}</a> — {pmid_text}</p>')
            else:
                pmid_block = (f'<p><em>({pmid_text} — '
                             f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pid}/" rel="noopener noreferrer">source</a>)</em></p>')

        body += f'\n<h2 id="sec{i}">{sec_name}</h2>\n{sec_img}\n{pmid_block}\n{clean_content}\n'

    # [v7.0] 섹션 루프 완료 후 캐시 클리어 (다음 포스트에 영향 없도록)
    if hasattr(assemble_post, "_pmid_sections_cache"):
        del assemble_post._pmid_sections_cache

    links_html = "\n".join([
        f'<p>&#8594; <a href="{l["url"]}" rel="noopener noreferrer">Also worth reading: {l["title"]}</a></p>'
        for l in related_links
    ])

    cliff_html = ""
    if include_cliff:
        cliff_styles = [
            (f'<div style="background:#fff8f0; border-left:4px solid #e67e22; padding:18px; margin:28px 0; border-radius:6px;">'
             f'<p style="margin:0; font-size:1.05em;">The one thing I kept underestimating with {topic_label} was how much timing mattered. '
             f'Everything else stayed the same — only the timing changed.</p></div>'),
            f"<p><em>There's one detail I didn't mention yet — and it's the part that changed my results the most.</em></p>",
            (f'<blockquote><p>One thing I overlooked for months with {topic_label}: '
             f'how my other daily habits were quietly cancelling out the effect.</p></blockquote>'),
            (f'<div style="background:#f0f7ff; border-left:4px solid #2a6496; padding:16px; margin:24px 0;">'
             f'<p style="margin:0;">One thing I underestimated was how my other supplements affected {topic_label}. '
             f'That interaction turned out to matter more than the dose itself.</p></div>'),
        ]
        cliff_html = random.choice(cliff_styles)

    faq_html = ""
    schema   = ""
    if include_faq:
        faq_pairs = parse_faq(faq_text)
        if len(faq_pairs) < 2:
            faq_pairs = [
                (f"What is the optimal dosage of {topic_label}?",
                 "Dosage varies by individual. Clinical studies suggest starting conservatively "
                 "and adjusting based on response. Consult a healthcare professional for personalized guidance."),
                (f"How long does {topic_label} take to show effects?",
                 "Most research reports measurable effects after 4-6 weeks of consistent use. "
                 "Individual results depend on baseline levels and lifestyle factors."),
                (f"Can {topic_label} be combined with other supplements?",
                 "Generally yes, though specific combinations require consideration of timing and interactions. "
                 "Always consult a healthcare professional before adding new supplements."),
            ]
        faq_html = f'<h2 id="faq">Frequently Asked Questions</h2>\n'
        for q, a in faq_pairs[:3]:
            cq = re.sub(r'<[^>]+>','',q).strip()
            ca = re.sub(r'<[^>]+>','',a).strip()
            faq_html += f'<h3>{cq}</h3>\n<p>{ca}</p>\n'
        schema = build_faq_schema(faq_pairs[:3])

    methodology = ""
    if include_meth:
        methodology = (
            '<div style="background:#f0f7ff;border-left:4px solid #4a90d9;padding:16px 20px;margin:24px 0;border-radius:4px;">'
            '<h2 style="margin-top:0;">About the Author</h2>'
            '<p><strong>Erik Lindström</strong> is a Stockholm-based writer who documents his personal supplement '
            'experiences and what has (or hasn\'t) worked in his own routine. '
            f'{random.choice(_AUTHOR_BIO_VARIANTS)}</p>'
            '<p style="margin-bottom:0;font-size:0.9em;color:#555;">'
            '<a href="https://www.nutristacklab.com/p/1-about-us-manifesto-of-nutristack-lab.html" rel="noopener noreferrer">More about Erik</a>'
            ' &nbsp;|&nbsp; '
            '<a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html" rel="noopener noreferrer">Medical Disclaimer</a>'
            ' &nbsp;|&nbsp; '
            '<a href="https://www.nutristacklab.com/p/3-privacy-policy-gdpr-compliant.html" rel="noopener noreferrer">Privacy Policy</a>'
            '</p></div>'
        )

    disclaimer = (
        '<p style="font-size:0.85em;color:#666666;border-top:1px solid #eee;padding-top:12px;">'
        '<em><strong>Medical Disclaimer:</strong> This content is for informational and educational purposes only '
        'and does not constitute medical advice, diagnosis, or treatment. '
        'Always consult a qualified healthcare provider before making changes to your supplement or nutrition routine. '
        'Read our full <a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html" '
        'rel="noopener noreferrer">Medical Disclaimer</a> and '
        '<a href="https://www.nutristacklab.com/p/3-privacy-policy-gdpr-compliant.html" '
        'rel="noopener noreferrer">Privacy Policy</a>.</em></p>'
    )

    parts = [disc, f'<h1>{clean_title}</h1>', hero, takeaways, hook_block, toc_html, body]
    parts.append(f'<hr>\n{links_html}\n<hr>')
    if cliff_html:  parts.append(cliff_html)
    if faq_html:    parts.append(faq_html)
    if methodology: parts.append(f'<hr>\n{methodology}')
    parts.append(f'<hr>\n{disclaimer}')
    final = "\n".join(p for p in parts if p)
    # [v5.9.5] CSS 색상 코드 복원 — style 속성 내부만 정밀 수술
    # border:1px solid ddd / background:f0f7ff 등 공백 뒤 hex도 처리
    def _fix_style_colors(m):
        s = m.group(1)
        # 6자리 hex (앞에 # 없는 것만)
        s = re.sub(r'(?<![#\w])([0-9a-fA-F]{6})(?=[;\s"\)])', r'#\1', s)
        # 3자리 hex (앞에 # 없는 것만, 숫자와 구분)
        s = re.sub(r'(?<![#\w])([0-9a-fA-F]{3})(?=[;\s"\)])', r'#\1', s)
        return f'style="{s}"'
    final = re.sub(r'style="([^"]*)"', _fix_style_colors, final)

    # [v6.2] Blogger 목록 썸네일용 숨김 이미지 — hero가 base64일 때만 주입
    if hero_url.startswith('data:'):
        topic_lower = topic.lower()
        thumb_desc = next(
            (v for k, v in IMAGE_STYLE_DB.items() if k in topic_lower),
            f"health supplement {topic_label} on a wooden kitchen counter, natural light"
        )
        thumb_url = (f"https://image.pollinations.ai/prompt/"
                     f"{requests.utils.quote(thumb_desc[:120])}"
                     f"?width=800&height=600&nologo=true")
        final = f'<img src="{thumb_url}" style="display:none;width:1px;height:1px;" alt="" />\n' + final

    # Return the original (non-truncated) title for Blogger API; clean_title is H1-only
    return final, schema, title

# ============================================================
# 품질 전처리 Sanitizer (무료 — API 호출 없음)
# ============================================================
def auto_sanitize_html(html: str, topic: str) -> str:
    """quality_check 전에 흔한 실패 패턴을 무료로 자동 수정."""
    # 1. Generic H1 수정: "complete guide" / "ultimate guide" 포함 시 교체
    def fix_h1(m):
        original = m.group(1)
        lower = original.lower()
        if "complete guide" in lower or "ultimate guide" in lower:
            core = re.sub(r'(?i)(the\s+)?(complete|ultimate)\s+guide\s*(to|for|on)?\s*', '', original).strip(' :-—')
            if not core:
                core = topic.replace(" Complete Guide","").replace(" Guide","").strip()
            return f"<h1>What I Found After Testing {core}: My Honest Notes</h1>"
        return m.group(0)
    html = re.sub(r'<h1[^>]*>(.+?)</h1>', fix_h1, html, flags=re.IGNORECASE | re.DOTALL)

    # 1-b. body 본문 "complete guide" / "ultimate guide" 제거 (AI_Footprint 사전 차단)
    # H1은 위에서 이미 교체됨. 본문 내 잔존 구절만 제거.
    html = re.sub(r'(?i)\b(the\s+)?(complete|ultimate)\s+guide\b', '', html)
    html = re.sub(r'  +', ' ', html)  # 이중 공백 정리

    # 2. 치료/완치 주장 → 부드러운 표현으로 교체 (No_Cure_Claims)
    cure_replacements = [
        (r'\bcures?\b', 'may support'),
        (r'\btreats?\s+(the\s+)?(symptoms?\s+of\s+)?\w+\s+disease\b', 'may help with certain conditions'),
        (r'\bprevents?\s+cancer\b', 'may support cellular health'),
        (r'\bheals?\s+\w+\s+condition\b', 'may support recovery'),
        (r'\bguaranteed\s+to\b', 'may'),
    ]
    for pattern, replacement in cure_replacements:
        html = re.sub(pattern, replacement, html, flags=re.IGNORECASE)

    # 3. 이미지 alt 정제 — 이중공백 + Alt_Clean 패턴 제거
    _alt_bad_inline = ["And Zinc","Stopped And","Taking And","Stop And","Take And","Trying And","Comparing And","Using And"]
    def fix_alt(m):
        a = re.sub(r' {2,}', ' ', m.group(1))
        a = re.sub(r'(?i)\s+and\s+(zinc|selenium|iron|copper|magnesium|calcium|potassium)(?=\s|$)', '', a)
        a = re.sub(r'(?i)^(and|or)\s+', '', a).strip()
        for bad in _alt_bad_inline:
            a = a.replace(bad, bad.split(' And ')[0] if ' And ' in bad else a)
        a = re.sub(r'\bAnd\b', 'and', a)
        return f'alt="{a.strip()}"'
    html = re.sub(r'alt="([^"]*)"', fix_alt, html)

    # 4. 영양소명 정확성 보장 — 토픽의 D3/K2/B12/MK-7 등이 본문에서 누락 시 자동 복원
    _idents = re.findall(r'\b([A-Z]{1,3}\d+(?:-\d+)?)\b', topic)
    _idents = list(dict.fromkeys(i for i in _idents if len(i) >= 2))
    for _ident in _idents:
        if re.search(r'\b' + re.escape(_ident) + r'\b', html, re.I):
            continue  # 이미 존재 — 건너뜀
        # 기본 형태 추출: D3 → base="D", suffix="3" / K2 → K, 2 / B12 → B, 12
        _base   = re.sub(r'\d.*$', '', _ident)
        _suffix = _ident[len(_base):]
        if not _base or not _suffix:
            continue
        # "Vitamin D" (뒤에 숫자 없음) → "Vitamin D3"
        _pat = r'\bVitamin\s+' + re.escape(_base) + r'\b'
        _count = len(re.findall(_pat, html, re.I))
        if _count:
            html = re.sub(_pat, lambda m: m.group(0) + _suffix, html, flags=re.I)
            logging.info(f"  [F1-AutoFix] 'Vitamin {_base}' → 'Vitamin {_ident}' {_count}곳 자동 보정")

    # 5. 토픽명 본문 오염 제거 — e.g., "Zinc Complete Guide" + "al creams" → "al creams"
    # AI가 "topical" 등의 단어에서 "topic" 부분을 토픽 전체 이름으로 치환하는 할루시네이션 방지
    _tp = topic.strip()
    if len(_tp) > 5:
        _tp_esc = re.escape(_tp)
        # 토픽명이 소문자로 시작하는 접미사와 붙은 경우 (오염) → 접미사만 남김
        _contam_hits = re.findall(r'\b' + _tp_esc + r'([a-z]\w*)', html, re.I)
        if _contam_hits:
            html = re.sub(r'\b' + _tp_esc + r'([a-z]\w*)', r'\1', html, flags=re.I)
            logging.info(f"  [ContamFix] 토픽명 오염 {len(_contam_hits)}건 제거: {_contam_hits[:2]}")
        # 토픽명이 <p>/<li> 본문에 단독으로 나타나는 경우도 제거
        _contam_standalone = re.findall(
            r'(?<![<\w])' + _tp_esc + r'(?![>\w])', html, re.I
        )
        if len(_contam_standalone) > 1:  # H1/H2 외 반복 등장 → 오염
            # 첫 번째(H1/H2 내)는 유지, 이후 반복 제거
            count = [0]
            def _keep_first(m):
                count[0] += 1
                return m.group(0) if count[0] == 1 else ''
            html = re.sub(r'(?<![<\w])' + _tp_esc + r'(?![>\w])', _keep_first, html, flags=re.I)
            logging.info(f"  [ContamFix] 토픽명 반복 {len(_contam_standalone)}건 → 1건 유지")

    # 6. Disclaimer 누락 시 자동 삽입
    if 'medical-disclaimer' not in html.lower():
        disclaimer_html = (
            '\n<div class="medical-disclaimer" style="background:#f9f9f9;border-left:4px solid #e0a800;'
            'padding:12px 16px;margin:24px 0;border-radius:4px;font-size:0.9em;">'
            '<strong>Medical Disclaimer:</strong> This content is for informational purposes only and '
            'does not constitute medical advice. Consult a qualified healthcare provider before making '
            'any changes to your supplement regimen.</div>\n'
        )
        # </body> 앞 또는 마지막에 삽입
        if '</body>' in html:
            html = html.replace('</body>', disclaimer_html + '</body>', 1)
        else:
            html = html + disclaimer_html

    return html


# ============================================================
# 품질 검사
# ============================================================
def _qa_leakage_issues(html: str) -> list:
    """Placeholder leakage / generic H1 / broken meta 탐지. 발견 시 즉시 반려."""
    issues = []
    text = re.sub(r'<[^>]+>', ' ', html)

    # 1. Placeholder leakage: 단어 사이 공백 2칸 이상 (빈 entity)
    if re.search(r'[A-Za-z]\s{2,}[A-Za-z]', text):
        snippet = re.search(r'[A-Za-z]\s{2,}[A-Za-z]', text).group()
        issues.append(f"Placeholder leakage(빈 entity): '{snippet}'")

    # 2. Generic H1 패턴
    h1_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
    if h1_m:
        h1 = h1_m.group(1).strip().lower()
        GENERIC_H1 = [
            "how i use supplement", "supplement effectively", "my findings",
            "how to use", "benefits of supplement", "everything you need",
            "ultimate guide", "the truth about supplement",
        ]
        # "complete guide" 단독일 때만 차단 (SAMe Complete Guide 등 정상 제목은 통과)
        is_generic_complete = re.fullmatch(r'(the\s+)?complete\s+guide(\s+to\s+\w+)?', h1)
        if any(p in h1 for p in GENERIC_H1) or is_generic_complete:
            issues.append(f"Generic H1 template: '{h1_m.group(1)[:60]}'")

    # 3. Meta description 누락 또는 비어있음
    meta_m = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    )
    if not meta_m or len(meta_m.group(1).strip()) < 20:
        issues.append("Meta description 누락 또는 너무 짧음")

    # 3-1. og:description 비어있음 체크
    og_m = re.search(
        r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    )
    if not og_m or len(og_m.group(1).strip()) < 20:
        issues.append("og:description 누락 또는 비어있음")

    # 4. 이미지 캡션 placeholder
    captions = re.findall(r'alt="([^"]*)"', html)
    for alt in captions:
        if re.search(r'[A-Za-z]\s{2,}[A-Za-z]', alt):
            issues.append(f"이미지 alt placeholder: '{alt[:40]}'")

    return issues


def passes_min_gates(html, word_count):
    # [v5.9.9.9] 애드센스 승인 및 품질 유지를 위한 절대 최소 기준 (1,000 Words)
    if word_count < 1000: return False
    if "Disclosure:" not in html: return False
    # 플레이스홀더 체크 (기존 BLOCK_TERMS 통합)
    BLOCK_TERMS = ["TOPIC:", "{topic}", "Discover how", "How I Use TOPIC"]
    if any(term in html for term in BLOCK_TERMS): return False
    # QA leakage 하드 차단
    if _qa_leakage_issues(html): return False
    return True

def has_repetitive_paragraphs(html):
    paras = re.findall(r'<p>(.*?)</p>', html)
    for i in range(len(paras) - 1):
        p1 = paras[i].strip()
        p2 = paras[i+1].strip()
        if len(p1) > 50 and p1 == p2:
            return True
    return False

def quality_check(html, title, archetype_name="science-heavy"):
    word_count = len(re.sub(r'<[^>]+>', ' ', html).split())
    logging.info(f"  📝 단어 수: {word_count}")
    min_words  = ARCHETYPES.get(archetype_name, {}).get("min_words", 1200)
    checks = {
        f"단어수_{min_words}+": word_count >= min_words,
        "H1 1개":          len(re.findall(r'<h1>',html)) == 1,
        "H1 60자":         len(title) <= 60,
        "Pollinations없음": 'pollinations.ai' not in html,
        "빈src없음":       'src=""' not in html,
        "&#8594;사용":     '&#8594;' in html,
        "Disclaimer":      'medical-disclaimer' in html.lower(),
        "Disclosure":      'Disclosure:' in html,
        "PersonaCheck":    'Erik Lindström' in html and 'NutriStack Lab Methodology' not in html,
        "PMID_Valid":      not any(len(p) < 7 for p in re.findall(r'PMID\s*(\d+)', html, re.IGNORECASE)),
        "AI_Footprint":    not any(p in html.lower() for p in ["interestingly", "notably", "surprisingly", "moreover", "furthermore", "magic hour", "consistency is king", "pairing routine", "delve into", "unlock the", "it's worth noting", "in conclusion", "to summarize", "as an ai", "i cannot", "crucial role", "multifaceted", "comprehensive overview", "let's explore", "in this article we will", "real talk:", "chemical architecture", "complete guide"]),
        "No_Cure_Claims":  not any(re.search(p, html, re.IGNORECASE) for p in [r'\bcures?\b', r'\btreats?\s+\w+\s+disease', r'\bprevents?\s+cancer\b', r'\bheals?\s+\w+\s+condition', r'\bguaranteed\s+to\b']),
        "Alt_Clean":       not any(bad in html for bad in ["And Zinc", "Stopped And", "Taking And", "Stop And", "Take And", "Trying And", "Comparing And", "Using And"]) and all(not alt.strip().startswith("And ") for alt in re.findall(r'alt="([^"]*)"', html)),
        "Repetition_Free": not has_repetitive_paragraphs(html),
        "NoPlaceholder":   not _qa_leakage_issues(html),
    }
    if archetype_name == "comprehensive-guide":
        checks["TOC_Present"] = 'href="#sec' in html
    score  = sum(checks.values()) / len(checks)
    issues = [k for k,v in checks.items() if not v]
    return score, issues, word_count

# ============================================================
# [v6.5] 수술적 섹션 보완 — 문제 섹션만 삭제하여 writer가 해당 섹션만 재작성
# ============================================================
# [v6.5] 동적 규칙 시스템 — 반복 실패에서 코드 규칙 자동 추출·적용
# ============================================================

def load_dynamic_rules() -> dict:
    if DYNAMIC_RULES_FILE.exists():
        try: return json.loads(DYNAMIC_RULES_FILE.read_text(encoding='utf-8'))
        except: pass
    return {"phrases": [], "section_performance": {}, "retry_history": []}

def save_dynamic_rules(rules: dict):
    DYNAMIC_RULES_FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding='utf-8')

def extract_ai_phrases_from_html(html: str) -> list:
    """반려된 HTML에서 AI 패턴 구절 자동 추출"""
    candidates = [
        r"it is (?:important|essential|crucial) to (?:note|mention|consider)",
        r"it(?:'s| is) worth (?:noting|mentioning)",
        r"as (?:previously|earlier) mentioned",
        r"needless to say",
        r"at the end of the day",
        r"all things considered",
        r"in other words",
        r"to (?:put it simply|summarize|conclude)",
        r"one must (?:note|consider|remember)",
        r"plays a (?:crucial|vital|key|pivotal) role",
        r"it goes without saying",
    ]
    found = []
    for pat in candidates:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            found.append(m.group(0).lower().strip())
    return found

def update_dynamic_rules_from_rejection(html: str, issues: list, critic_result: str):
    """반려 시마다 새 금지 구절 추출 → 코드 레벨 규칙으로 승격"""
    if "AI_Footprint" not in issues:
        return
    rules = load_dynamic_rules()
    new_phrases = [p for p in extract_ai_phrases_from_html(html)
                   if p not in rules["phrases"] and p not in _AI_PHRASES]
    if new_phrases:
        rules["phrases"].extend(new_phrases)
        rules["phrases"] = list(dict.fromkeys(rules["phrases"]))[-60:]
        save_dynamic_rules(rules)
        logging.info(f"  📋 [동적규칙] 금지구절 {len(new_phrases)}개 추가: {new_phrases}")

def record_section_removal(section_name: str, issues: list, critic_reason: str):
    """섹션 제거 통계 기록 — 반복 약점 파악"""
    rules = load_dynamic_rules()
    perf  = rules.setdefault("section_performance", {})
    entry = perf.setdefault(section_name, {"removed": 0, "issues": [], "top_issue": ""})
    entry["removed"] += 1
    entry["issues"]   = (entry["issues"] + issues)[-30:]
    # 가장 빈번한 이슈를 top_issue로 기록
    if entry["issues"]:
        from collections import Counter
        entry["top_issue"] = Counter(entry["issues"]).most_common(1)[0][0]
    save_dynamic_rules(rules)

def get_section_extra_guidance(section_name: str) -> str:
    """반복 실패 섹션에 대한 추가 가이던스 반환"""
    rules = load_dynamic_rules()
    data  = rules.get("section_performance", {}).get(section_name, {})
    count = data.get("removed", 0)
    if count < 2:
        return ""
    top   = data.get("top_issue", "")
    lines = [f"⚠️ This section has been rewritten {count} times. Get it right this time."]
    if top == "AI_Footprint":
        lines.append("CRITICAL: Past versions were too AI-sounding. Write raw, imperfect, human. Use fragments. Say 'I' a lot.")
    elif top == "Repetition_Free":
        lines.append("CRITICAL: Past versions repeated content from other sections. Bring a completely new angle.")
    elif top and "단어수" in top:
        lines.append("CRITICAL: Past versions were too short. Write more — go deeper, add personal details, expand examples.")
    return " ".join(lines)

def record_retry_effectiveness(topic: str, retry_count: int, published: bool):
    """API 절감 효과 측정 — 재시도 횟수 추적"""
    rules = load_dynamic_rules()
    hist  = rules.setdefault("retry_history", [])
    hist.append({"date": datetime.now().strftime("%Y-%m-%d"), "topic": topic[:40],
                 "retries": retry_count, "published": published})
    rules["retry_history"] = hist[-100:]
    avg = sum(h["retries"] for h in hist[-20:]) / max(len(hist[-20:]), 1)
    rules["avg_retries_20"] = round(avg, 2)
    save_dynamic_rules(rules)
    logging.info(f"  📊 [효과측정] 재시도 {retry_count}회 | 최근20편 평균: {avg:.1f}회")

def sanitize_section_content(content: str) -> str:
    """LLM 생성 직후 섹션에서 AI 구절 즉시 제거 (코드 레벨 강제)"""
    all_phrases = _AI_PHRASES + load_dynamic_rules().get("phrases", [])
    for phrase in all_phrases:
        content = re.sub(r'(?i)\b' + re.escape(phrase) + r'\b[,.]?', '', content)
    return re.sub(r'  +', ' ', content).strip()

# 시작 시 동적 규칙을 _AI_PHRASES에 병합
_AI_PHRASES = ["interestingly","notably","surprisingly","moreover","furthermore",
               "magic hour","consistency is king","pairing routine","delve into",
               "unlock the","it's worth noting","in conclusion","to summarize",
               "as an ai","i cannot","crucial role","multifaceted",
               "comprehensive overview","let's explore","in this article we will"]
try:
    _dynamic_phrases = load_dynamic_rules().get("phrases", [])
    _AI_PHRASES = list(dict.fromkeys(_AI_PHRASES + _dynamic_phrases))
    if _dynamic_phrases:
        logging.info(f"  📋 [동적규칙] 금지구절 {len(_dynamic_phrases)}개 로드")
except Exception:
    pass

def surgical_remove_sections(sections: dict, issues: list, critic_feedback: str) -> dict:
    """문제 있는 섹션만 ctx에서 제거 — 나머지는 재사용."""
    if not sections:
        return sections

    to_remove = set()

    # 1. AI_Footprint: 금지 구절 포함 섹션만 제거
    if "AI_Footprint" in issues:
        for sec, content in sections.items():
            if any(p in content.lower() for p in _AI_PHRASES):
                to_remove.add(sec)

    # 2. Repetition_Free: 앞 섹션과 내용 중복되는 섹션 제거
    if "Repetition_Free" in issues:
        items = list(sections.items())
        for i in range(1, len(items)):
            prev_words = set(re.sub(r'<[^>]+>',' ', items[i-1][1]).lower().split())
            curr_words = set(re.sub(r'<[^>]+>',' ', items[i][1]).lower().split())
            common = prev_words & curr_words - {'the','a','an','and','or','of','in','to','is','it','this','that','for','with','on','at','by'}
            if len(common) / max(len(curr_words), 1) > 0.45:
                to_remove.add(items[i][0])

    # 3. Critic 피드백에서 언급된 섹션명 찾아서 제거
    feedback_lower = critic_feedback.lower()
    for sec in sections:
        # 섹션 제목 첫 두 단어 중 의미있는 단어가 피드백에 언급되면 해당 섹션 제거
        sig_words = [w for w in sec.lower().split() if len(w) > 4][:2]
        if sig_words and any(w in feedback_lower for w in sig_words):
            to_remove.add(sec)

    # 4. 아무것도 못 찾았으면 단어 수 가장 적은 섹션 1개만 제거
    if not to_remove:
        word_counts = {s: len(re.sub(r'<[^>]+>',' ', c).split()) for s, c in sections.items()}
        weakest = min(word_counts, key=word_counts.get)
        to_remove.add(weakest)

    removed = list(to_remove)
    for sec in to_remove:
        sections.pop(sec, None)
        record_section_removal(sec, issues, critic_feedback[:200])  # 약점 통계 기록

    logging.info(f"  🔧 [Surgical] 재작성 대상 섹션 {len(removed)}개: {removed}")
    return sections

# ============================================================
# Obsidian 학습 기록
# ============================================================
def save_learning(topic, title, status, issues, score, archetype_name, topic_type, ctx=None):
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    ctx      = ctx or {}
    nutrients   = extract_nutrients_from_topic(topic)
    wiki_links  = " | ".join([f"[[{n.title()}]]" for n in nutrients[:5]]) if nutrients else "없음"
    sections    = ctx.get("sections", {})
    total_words = sum(len(re.sub(r'<[^>]+>',' ', v).split()) for v in sections.values())
    issues_md   = "\n".join([f"- {i}" for i in issues]) if issues else "- 없음"
    md = f"""# {title}

## 📊 발행 정보
| 항목 | 내용 |
|------|------|
| **날짜** | {date_str} |
| **주제** | {topic} |
| **아키타입** | {archetype_name} |
| **주제 타입** | {topic_type} |
| **상태** | {'✅ 성공' if status == 'success' else '❌ 실패'} |
| **품질 점수** | {score:.1%} |
| **단어 수** | {total_words:,} |

## 🔗 관련 영양소
{wiki_links}

## ⚠️ 이슈
{issues_md}

---
*NutriStack Lab v5.4 자동 기록*
"""
    safe_topic = re.sub(r'[\\/*?:"<>|]', '', topic)[:25].replace(' ', '_')
    fp = LEARN_DIR / f"{ts}_{status}_{safe_topic}.md"
    fp.write_text(md, encoding='utf-8')
    logging.info(f"  📚 옵시디언 기록: {fp.name}")

    perf_file = META_DIR / "performance_db.json"
    perf_db   = []
    if perf_file.exists():
        try: perf_db = json.loads(perf_file.read_text(encoding='utf-8'))
        except: pass
    perf_db.append({
        "date": date_str, "topic": topic, "title": title,
        "status": status, "score": score, "word_count": total_words,
        "archetype": archetype_name, "topic_type": topic_type,
        "nutrients": nutrients, "category": detect_category(topic), "issues": issues
    })
    perf_db = perf_db[-200:]
    perf_file.write_text(json.dumps(perf_db, ensure_ascii=False, indent=2), encoding='utf-8')

# ============================================================
# Blogger 발행
# ============================================================
def _strip_html_document_wrapper(content: str) -> str:
    """AI가 <!DOCTYPE html> 전체 문서를 생성했을 때 body 내용만 추출.
    SEO 블록(DOCTYPE 이전) + <style> 블록 + body 내용으로 재조합."""
    import html as _hl
    doctype_pos = content.find('<!DOCTYPE')
    if doctype_pos == -1:
        doctype_pos = content.lower().find('<html')
    if doctype_pos == -1:
        return _hl.unescape(content)

    seo_block = content[:doctype_pos].strip()

    style_m = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL | re.IGNORECASE)
    style_block = ""
    if style_m:
        sc = style_m.group(1)
        sc = re.sub(r'\.toc\s+li::?before\s*\{[^}]*\}', '', sc, flags=re.DOTALL)
        sc = re.sub(r'\n{3,}', '\n\n', sc)
        style_block = f'<style>\n{sc}\n</style>\n' if sc.strip() else ''

    body_pos = content.lower().find('<body')
    if body_pos != -1:
        body_tag_end = content.index('>', body_pos) + 1
        close = max(content.rfind('</body>'), content.rfind('</html>'))
        body_text = content[body_tag_end:close if close > body_tag_end else len(content)].strip()
    else:
        body_text = content[doctype_pos:]

    cleaned = (seo_block + '\n' + style_block + body_text).strip()
    logging.warning("  ⚠️ [발행] <!DOCTYPE html> 구조 감지 → body 내용만 추출")
    return _hl.unescape(cleaned)


# ── [M2.7 Surgical Fix] 발행 전 메타/오염 부분 수술 ───────────────────────────
def minimax_surgical_fix(html: str, title: str, topic: str) -> str:
    """
    Qwen3 초안 발행 직전 M2.7로 부분 수술.
    내용 재작성 없이 메타/오염 패턴만 정밀 수정.
    """
    prompt = f"""You are an editorial assistant doing a SURGICAL fix on a blog post.
DO NOT rewrite content. Only fix these specific issues if present:

1. TITLE: If title contains "Benefits, Dosage", "How to Take", "Complete Guide", "Worth Taking",
   "Research Says" → replace with a personal experience title
2. OG:DESCRIPTION: If it sounds clinical/research-like → make it first-person experience
3. AI PHRASES: Replace any of these exact phrases:
   - "HMB reducing muscle breakdown" → "HMB may support recovery"
   - "copper and vitamin C don't play well together" → "separating them worked better for me"
   - "inflammation markers were lower" → "blood work looked better overall"
   - "zinc was quietly rewriting how my body functioned" → "my body seemed to slowly adjust"
   - "recovery improved noticeably" → "I seemed to recover a little better"
   - "preventing muscle loss" → "possibly supporting muscle retention"
4. MECHANISM CLAIMS: Any sentence stating supplement mechanism as fact → add "from what I read" or "it seemed like"

Return the COMPLETE HTML with ONLY those targeted fixes applied. Nothing else changed.

POST TITLE: {title}
TOPIC: {topic}

HTML:
{html[:8000]}"""

    fixed = ask_minimax(prompt, "Fix only what's listed. Return complete HTML.", MODEL_MINIMAX_SURGEON, max_tokens=8192)
    if fixed and len(fixed) > 1000 and '<' in fixed:
        logging.info(f"  ✂️ [M2.7 수술] 메타/오염 패턴 수정 완료")
        return fixed
    logging.warning(f"  ✂️ [M2.7 수술] 응답 불량 — 원본 유지")
    return html
# ─────────────────────────────────────────────────────────────────────────────


# ── [SEO Ping] 발행 시 검색엔진 알림 ──────────────────────────────────────────
_SITEMAP_URL  = "https://www.nutristacklab.com/sitemap.xml"
_GSC_SITE_URL = "sc-domain:nutristacklab.com"

def _load_bing_key() -> str:
    if os.environ.get("BING_API_KEY"):
        return os.environ["BING_API_KEY"]
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BING_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    os.environ["BING_API_KEY"] = key
                    return key
    return ""

def ping_indexing(post_url: str):
    """발행 완료 직후 Google SC 사이트맵 제출 + Bing URL 직접 등록 (비치명적)."""
    results = []

    # 1. Google Search Console — 사이트맵 제출
    try:
        creds = get_creds()
        wm = build("webmasters", "v3", credentials=creds)
        wm.sitemaps().submit(siteUrl=_GSC_SITE_URL, feedpath=_SITEMAP_URL).execute()
        results.append("Google SC ✅")
    except Exception as e:
        results.append(f"Google SC ❌ {e}")

    # 2. Bing Webmaster Tools — 사이트맵 제출 + URL 직접 등록
    _bing_key = _load_bing_key()
    if _bing_key:
        # 2-a. 사이트맵 제출
        try:
            r = requests.post(
                f"https://ssl.bing.com/webmaster/api.svc/json/AddSitemap?apikey={_bing_key}",
                headers={"Content-Type": "application/json; charset=utf-8"},
                json={"siteUrl": "https://www.nutristacklab.com/", "feedUrl": _SITEMAP_URL},
                timeout=10,
            )
            results.append(f"Bing Sitemap ✅ ({r.status_code})" if r.ok else f"Bing Sitemap ❌ ({r.status_code})")
        except Exception as e:
            results.append(f"Bing Sitemap ❌ {e}")
        # 2-b. 신규 URL 직접 등록
        try:
            r = requests.post(
                f"https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlbatch?apikey={_bing_key}",
                headers={"Content-Type": "application/json; charset=utf-8"},
                json={"siteUrl": "https://www.nutristacklab.com/", "urlList": [post_url]},
                timeout=10,
            )
            results.append(f"Bing URL ✅ ({r.status_code})" if r.ok else f"Bing URL ❌ ({r.status_code}) {r.text[:80]}")
        except Exception as e:
            results.append(f"Bing URL ❌ {e}")
    else:
        results.append("Bing ⏭️ (키 없음)")

    logging.info(f"  🔍 [Ping] {' | '.join(results)}")
# ─────────────────────────────────────────────────────────────────────────────


def publish_to_blogger(title, content, labels=[], meta_desc="", is_draft=False, post_id=None, url_seed=None):
    """
    url_seed: 신규 포스트 최초 발행 시 인간형 URL을 만들기 위한 짧은 슬러그 제목.
              설정 시 이 제목으로 먼저 insert → URL 생성 → 즉시 실제 title로 update.
    """
    svc = get_blogger_service()
    if not svc: return False
    content = _strip_html_document_wrapper(content)
    clean_title  = title.strip()[:200]
    clean_labels = []
    for l in labels[:10]:
        ls = str(l).strip()
        if len(ls) > 50 or '\n' in ls or '**' in ls: continue
        lc = re.sub(r'[^\w\-]','',ls)[:50]
        if lc: clean_labels.append(lc)
    if not clean_labels:
        clean_labels = ["Supplements","NordicHealth","NutriStackLab"]
    
    _search_desc = meta_desc.strip()[:150] if meta_desc and meta_desc.strip() else f"My personal research notes on {clean_title[:100]}."
    body = {
        "title": clean_title,
        "content": content,
        "labels": clean_labels,
        "searchDescription": _search_desc,
    }
    
    if post_id:
        logging.info(f"  📤 제자리 수정 업데이트 (Post ID: {post_id}): {clean_title[:55]}")
        try:
            res = svc.posts().update(blogId=BLOG_ID, postId=post_id, body=body).execute()
            return res.get('url', res.get('id','published'))
        except Exception as e:
            logging.error(f"  Blogger 업데이트 오류: {e}")
            try:
                body.pop("labels",None)
                res = svc.posts().update(blogId=BLOG_ID, postId=post_id, body=body).execute()
                logging.info("  ✅ 라벨 없이 업데이트 성공")
                return res.get('url', res.get('id','published'))
            except Exception as e2:
                logging.error(f"  업데이트 재시도 실패: {e2}"); return False
    else:
        logging.info(f"  📤 신규 발행: {clean_title[:55]}")
        logging.info(f"  🏷️ 라벨: {clean_labels}")
        if is_draft: logging.info("  🛡️ Draft 모드로 발행합니다.")
        try:
            # [v7.0] URL 인간화: url_seed로 먼저 발행 → 인간형 URL 생성 → 실제 제목으로 즉시 업데이트
            _insert_body = dict(body)
            if url_seed and not is_draft:
                _insert_body["title"] = url_seed[:120]
                logging.info(f"  🔗 URL 슬러그 제목으로 발행: '{url_seed[:60]}'")
            res = svc.posts().insert(blogId=BLOG_ID, body=_insert_body, isDraft=is_draft).execute()
            _url = res.get('url', res.get('id','published'))
            _pid = res.get('id', '')
            # url_seed 사용한 경우 즉시 실제 제목으로 업데이트
            if url_seed and not is_draft and _pid:
                try:
                    svc.posts().update(blogId=BLOG_ID, postId=_pid, body=body).execute()
                    logging.info(f"  ✅ 실제 제목으로 업데이트: '{clean_title[:55]}'")
                except Exception as _ue:
                    logging.warning(f"  ⚠️ 제목 업데이트 실패 (URL은 정상): {_ue}")
            # post_id를 임시 파일로 저장 (audit_queue에서 사용)
            try:
                (META_DIR / "_last_post_id.txt").write_text(_pid, encoding="utf-8")
            except: pass
            return _url
        except Exception as e:
            logging.error(f"  Blogger 오류: {e}")
            try:
                body.pop("labels",None)
                res = svc.posts().insert(blogId=BLOG_ID,body=body,isDraft=is_draft).execute()
                logging.info("  ✅ 라벨 없이 재발행 성공")
                _url = res.get('url', res.get('id','published'))
                _pid = res.get('id', '')
                try:
                    (META_DIR / "_last_post_id.txt").write_text(_pid, encoding="utf-8")
                except: pass
                return _url
            except Exception as e2:
                logging.error(f"  재발행 실패: {e2}"); return False

# ============================================================
# 메인 오케스트레이터 v5.4
# ============================================================
class GrandOrchestrator:
    def __init__(self):
        self.ctx = {}
        self.rejection_history = []

    def run(self, file_path):
        self.ctx = {} # [🚨 v5.6] 새로운 미션 시작 시 메모리 초기화 필수
        if not file_path.exists():

            logging.error(f"  ❌ 파일을 찾을 수 없음: {file_path}")
            return False

        # v5.5: 파일은 딱 한 번만 읽고 루프로 진입
        raw_text = file_path.read_text(encoding='utf-8').strip()
        # draft 모드: 00_Test 폴더 OR 파일명에 test_ OR 헤더에 draft:true
        _raw_lines_hdr = raw_text.splitlines()[:8]
        _has_draft_hdr = any(
            l.strip().lower() in ("draft: true", "draft:true", "test: true")
            for l in _raw_lines_hdr
        )
        _is_test_file  = (file_path.parent == TEST_DIR)
        is_draft_mode  = _is_test_file or ("test_" in file_path.name.lower()) or _has_draft_hdr
        if is_draft_mode:
            logging.info(
                f"  🧪 [{'TEST FOLDER' if _is_test_file else 'DRAFT MODE'}] "
                f"초안으로만 저장됩니다 (발행 안 됨)"
            )
        
        while True: # [🚨 v5.5] 재귀 대신 루프 사용


            topic = ""
            task_type = "NEW" # 기본값

            # 파일명에서 태스크 타입 추출
            if "[REWRITE]" in file_path.name: task_type = "REWRITE"
            elif "[RESTORE_IMAGE]" in file_path.name: task_type = "RESTORE_IMAGE"

            # [v5.7] Ghost Purge: BOM/제어문자 제거 (ASCII 강제변환 금지 — 한국어 topic 파괴됨)
            topic = raw_text
            topic = topic.lstrip('﻿​‌‍')          # BOM + zero-width chars
            topic = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', topic)  # 제어문자
            # 헤더 라인 제거 (topic_type: / scheduled_time: / type: 등)
            topic = re.sub(r'^(topic_type|scheduled_time|draft|test|type|nutrients|category):[^\n]*\n?', '',
                           topic, flags=re.IGNORECASE | re.MULTILINE).strip()
            # 마크다운 H1 # 접두사 제거
            topic = re.sub(r'^#+\s*', '', topic, flags=re.MULTILINE).strip()
            # 접두사 청소 루프
            prefixes = [r'^TOPIC:\s*', r'^Title:\s*', r'^\[.*?\]', r'^P[12]\s*[-_]*\s*']
            for p in prefixes:
                topic = re.sub(p, '', topic, flags=re.IGNORECASE | re.MULTILINE).strip()
            
            topic = topic.replace("_"," ").replace("-"," ").strip()
            # 최종 확인: 혹시라도 남아있을 'TOPIC:' 단어 제거
            topic = re.sub(r'(?i)topic:\s*', '', topic).strip()

            # [v7.2] 빈/플레이스홀더 topic 차단 — 한국어만 남거나 비어있으면 발행 불가
            _ascii_words = [w for w in topic.split() if re.sub(r'[^\w]','',w) and w.isascii()]
            _is_placeholder = (
                not topic                                              # 완전 빈 문자열
                or not _ascii_words                                    # ASCII 단어 하나도 없음 (=순수 한국어)
                or topic.lower().strip() in ('supplement', 'supplements', 'nutrient', 'nutrients')
                or re.search(r'포스팅.*직전|실시간.*트렌드|생성됨', topic)  # 플레이스홀더 패턴
            )
            if _is_placeholder:
                logging.error(
                    f"  ❌ [v7.2] Topic이 비어있거나 플레이스홀더 — 발행 차단: '{topic[:60]}'"
                )
                try:
                    _skip_dest = COMPLETED_DIR / ("SKIPPED_BLANK_TOPIC_" + file_path.name)
                    if file_path.exists(): file_path.rename(_skip_dest)
                except Exception: pass
                return False

            self.ctx["task_type"] = task_type

            if task_type != "NEW":
                logging.info(f"  🛠️ 특수 태스크 감지: {task_type}")

            is_dup, dup_title = is_duplicate(topic)
            # REWRITE/RESTORE_IMAGE/DRAFT 는 의도적으로 기발행 글을 재처리 → 중복 체크 면제
            if is_dup and task_type == "NEW" and not is_draft_mode:

                logging.warning(f"  ⚠️ 중복 건너뜀: {dup_title[:40]}")
                try:
                    dest = COMPLETED_DIR / file_path.name
                    if dest.exists(): dest.unlink()
                    if file_path.exists(): file_path.rename(dest)
                except: pass
                return False
            elif is_dup and task_type in ("REWRITE", "RESTORE_IMAGE"):
                logging.info(f"  🔄 {task_type} 태스크: 중복 체크 면제 → 재처리 진행")

            cp = CHECKPOINT_DIR / f"{file_path.stem}.json"
            if cp.exists():
                try:
                    self.ctx = json.loads(cp.read_text(encoding='utf-8'))
                    logging.info(f"  ♻️ 체크포인트 복원")
                except: self.ctx = {}

            retries            = self.ctx.get("critic_retries", 0)
            is_mutation_needed = (retries > 0 and not self.ctx.get("sections"))

            if "archetype_name" not in self.ctx or is_mutation_needed:
                # RAW 파일 헤더에서 topic_type 우선 읽기
                _hdr_type = next(
                    (l.split(":",1)[1].strip() for l in _raw_lines_hdr
                     if l.startswith("topic_type:")),
                    None
                )
                topic_type = _hdr_type if _hdr_type else detect_topic_type(topic)
                if _hdr_type:
                    logging.info(f"  📌 topic_type 헤더 감지: {topic_type}")
                # [v6.0] 완전 가이드는 항상 comprehensive-guide 아키타입 강제
                if topic_type == "comprehensive_guide":
                    archetype_name = "comprehensive-guide"
                else:
                    archetype_name = pick_archetype()
                archetype_cfg  = get_archetype_config(archetype_name, topic_type)
                self.ctx["archetype_name"] = archetype_name
                self.ctx["archetype_cfg"]  = archetype_cfg
                self.ctx["topic_type"]     = topic_type
                if is_mutation_needed: logging.info(f"  ♻️ [Mutation] 아키타입 변이: {archetype_name}")
            else:
                archetype_name = self.ctx["archetype_name"]
                archetype_cfg  = self.ctx["archetype_cfg"]
                topic_type     = self.ctx["topic_type"]

            if "sections_list" not in self.ctx or is_mutation_needed:
                sections_list = get_sections_for_type(topic_type, archetype_cfg["section_count"])
                self.ctx["sections_list"] = sections_list
                if is_mutation_needed: logging.info(f"  ♻️ [Mutation] 섹션 변이: {sections_list}")
                # 선택된 가이드 템플릿 톤 저장 (Writer 프롬프트 주입용)
                if topic_type == "comprehensive_guide":
                    try:
                        _tmpl_info = json.loads((META_DIR / "last_guide_template.json").read_text(encoding="utf-8"))
                        self.ctx["guide_template_label"] = _tmpl_info.get("label", "")
                        self.ctx["guide_template_tone"]  = COMPREHENSIVE_GUIDE_TEMPLATES.get(
                            _tmpl_info.get("template", ""), {}
                        ).get("tone", "")
                    except Exception:
                        pass
            else:
                sections_list = self.ctx["sections_list"]

            logging.info(f"\n{'='*50}")
            logging.info(f"🚀 미션: {topic}")
            logging.info(f"  📐 아키타입: {archetype_name} / 📂 {topic_type}")
            logging.info(f"  📝 목표 단어: {archetype_cfg['target_words']} / 📑 섹션: {archetype_cfg['section_count']}")
            logging.info(f"  ❓ FAQ: {archetype_cfg['include_faq']} / 📋 TOC: {archetype_cfg['include_toc']}")
            logging.info(f"{'='*50}")

            report_to_discord("Chronos-X",
                f"🚀 **{topic}**\n📐 {archetype_name}/{topic_type}\n"
                f"📝 {archetype_cfg['target_words']}단어 목표")

            def save():
                cp.write_text(json.dumps(self.ctx,ensure_ascii=False,indent=2),encoding='utf-8')

            # Step 1: 리서치 [gemma4:e4b-it-q8_0]
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            # Step 1: 리서치 [gemma4:e4b-it-q8_0]
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            if "research" not in self.ctx:
                logging.info(f"📚 Step 1: 리서치 [gemma4 Q8]...")
                report_to_discord("리서처", f"📚 리서치 시작\n주제: {topic}")
                sys_p = load_agent_with_lessons("02_Researcher_Synergy.md")
                try:
                    from learning_engine import get_prompt_context
                    learn_ctx = get_prompt_context()
                except: learn_ctx = ""
                
                # [v6.0] 완전 가이드는 6개 섹션 전체 커버 리서치
                if topic_type == "comprehensive_guide":
                    research_prompt = (
                        f"Topic: {topic}\nArticle Type: COMPREHENSIVE GUIDE\n"
                        f"Research ALL of the following for this nutrient/supplement:\n"
                        f"1. OVERVIEW: what it is, why people are deficient, key symptoms of deficiency\n"
                        f"2. MECHANISM: how it works at cellular/molecular level, key enzymes/receptors involved\n"
                        f"3. SYNERGY: top 3-5 nutrients that enhance its effect, mechanisms of synergy\n"
                        f"4. ANTAGONISM: what blocks absorption, dangerous combinations, timing conflicts\n"
                        f"5. PROTOCOL: optimal dose, best form (glycinate/citrate/etc), timing, cycling\n"
                        f"6. TIMELINE: realistic expectations, when to feel effects, what changes first\n"
                        f"Include clinical dosages, bioavailability data, max 2 PMIDs.\n{learn_ctx}"
                    )
                else:
                    research_prompt = (
                        f"Topic: {topic}\nArticle Type: {archetype_name} / {topic_type}\n"
                        f"Research this health topic for a Nordic supplement blog.\n"
                        f"Focus: mechanisms, clinical evidence, {topic_type} context, practical application.\n"
                        f"Include: specific enzyme names, receptor interactions, clinical dosages.\n{learn_ctx}"
                    )
                self.ctx["research"] = ask_ai(research_prompt, sys_p, MODEL_RESEARCH)
                save()
            report_to_discord("리서처", "✅ 리서치 완료 → 섹션 작성 시작")

            # Step 2: 섹션 작성 [qwen2.5:14b]
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            writer_agent  = load_agent_with_lessons("03_Writer_Gardener.md", topic_type=topic_type)
            # Diversity hint: 과포화 구조 회피 지시 주입
            try:
                from diversity_checker import get_diversity_hint
                _div_hint = get_diversity_hint()
                if _div_hint.get("prompt_injection"):
                    writer_agent = writer_agent + "\n\n" + _div_hint["prompt_injection"]
                    logging.info(f"  [Diversity] Writer 프롬프트에 구조 회피 힌트 주입: avoid={_div_hint['avoid_arcs']}")
            except Exception as _dh_err:
                logging.warning(f"  [Diversity] 힌트 주입 실패 (무시): {_dh_err}")

            words_per_sec = max(200, min(600, archetype_cfg["target_words"] // len(sections_list)))
            last_feedback = self.ctx.get("last_critic_feedback","")
            feedback_instruction = (f"[CRITICAL: PREVIOUS REJECTION]\n{last_feedback}\nFIX THESE."
                                    if last_feedback else "")

            if "sections" not in self.ctx: self.ctx["sections"] = {}

            for sec in sections_list:
                if sec not in self.ctx["sections"]:
                    jitter        = random.uniform(0.85, 1.15)
                    current_words = int(words_per_sec * jitter)

                    density_instr = "Focus on practical outcomes and human experience. Use short paragraphs. BANNED: jargon (receptor, pathway, etc.)"
                    tone_instr = "Write like a Reddit user sharing their routine. Be casual and direct. Avoid AI adverbs (honestly, surprisingly). Use fragments for impact."

                    if archetype_name in ["minimalist","quick-answer","journal-tone"]:
                        density_instr = "Extremely light. Focus only on one core question. No science."
                        tone_instr += " Very casual. Like a text message to a friend."
                    elif archetype_name == "nordic-anecdotal":
                        density_instr = "Subtle science through daily living."
                        tone_instr += " Simple, direct observations."

                    # [v6.5] 반복 실패 섹션 추가 가이던스 로드
                    _sec_extra = get_section_extra_guidance(sec)
                    if _sec_extra:
                        logging.info(f"  ⚠️ [약점섹션] {sec} — 강화 가이던스 적용")
                        current_words = int(current_words * 1.2)  # 단어 수 20% 증가

                    logging.info(f"  ✍️ {sec} [{archetype_name}] ({current_words} words)")
                    report_to_discord("작가", f"✍️ 섹션 작성 중: {sec} ({current_words} words)")

                    # [v5.9.9.7] 표 제외 지시 반영 (Chaos Factor)
                    table_instruction = "" if archetype_cfg.get("include_table", True) else "\nSTRICT: DO NOT include any HTML tables in this section."

                    _guide_tmpl_instr = ""
                    if topic_type == "comprehensive_guide" and self.ctx.get("guide_template_tone"):
                        _guide_tmpl_instr = (
                            f"\nGUIDE NARRATIVE TEMPLATE: {self.ctx.get('guide_template_label','')}\n"
                            f"NARRATIVE TONE: {self.ctx.get('guide_template_tone','')}\n"
                            f"Write this section consistent with the above narrative arc. "
                            f"Do NOT mention combinations with other supplements or synergy stacks — "
                            f"focus only on mechanism, personal experience, dose/timing, and timeline.\n"
                        )

                    sec_sys_dynamic = (
                        f"{writer_agent}\n\n{feedback_instruction}\n\n"
                        f"{_sec_extra}\n\n"
                        f"ARTICLE ARCHETYPE: {archetype_name}\n"
                        f"TOPIC TYPE: {topic_type}\n"
                        f"TARGET: {current_words} words per section\n"
                        f"HUMAN TONE: {tone_instr}\n"
                        f"{_guide_tmpl_instr}"
                        f"CRITICAL: ONE SECTION ONLY. HTML <p> tags ONLY. NO markdown. NO headers.{table_instruction}\n"
                        f"Research context: {self.ctx.get('research','')[:1500]}"
                    )
                    _raw_section = ask_ai(
                        f"Write the '{sec}' section for: {topic}\n"
                        f"Article type: {archetype_name} / Topic type: {topic_type}\n"
                        f"Target: {current_words} words. HTML <p> tags only.\n{density_instr}",
                        sec_sys_dynamic, MODEL_WRITER
                    )
                    # [v6.5] 생성 직후 AI 구절 코드 레벨 제거 (LLM 무시해도 강제 차단)
                    self.ctx["sections"][sec] = sanitize_section_content(_raw_section)
                    save()

            # Step 3: 이미지 [SDXL hero / SD1.5 sections]
            report_to_discord("작가", f"✅ 전체 섹션 작성 완료 → 이미지 생성 시작")
            if "images" not in self.ctx: self.ctx["images"] = {}
            img_count = archetype_cfg["image_count"]

            if "hero" not in self.ctx["images"]:
                _img_title = self.ctx.get("title", "")
                _img_hook  = self.ctx.get("hook", "")
                img_desc = get_image_prompt(topic, "hero", title=_img_title, hook=_img_hook)
                fn = f"{file_path.stem}_hero.png"
                self.ctx["images"]["hero"] = get_image_url(img_desc, fn, IMAGE_DIR / fn)
                save()

            for i in range(1, min(img_count, len(sections_list)+1)):
                key = f"s{i}"
                if key not in self.ctx["images"]:
                    _img_title = self.ctx.get("title", "")
                    _img_hook  = self.ctx.get("hook", "")
                    img_desc = get_image_prompt(topic, key, title=_img_title, hook=_img_hook)
                    fn = f"{file_path.stem}_{key}.png"
                    self.ctx["images"][key] = get_image_url(img_desc, fn, IMAGE_DIR / fn)
                    save()

            # Step 4: Hook (v5.6 10종 로테이션)
            if "hook" not in self.ctx:
                pattern = get_next_pattern(HOOK_PATTERNS, "last_hook_pattern.json")
                logging.info(f"  🎣 Hook [v5.6 패턴: {pattern['id']}]...")
                report_to_discord("페르소나", f"🎣 훅(Hook) 작성 중... (패턴: {pattern['id']})")
                persona_sys = load_agent_with_lessons("06_Persona_Guardian.md")
                
                hook_instruction = pattern["instruction"]
                hook_creative = ask_ai(
                    f"Topic: {topic}\nPATTERN: {hook_instruction}\n"
                    f"Rules: 2nd person, end with tension, NO solution, 100-140 words.\nPlain text only.",
                    persona_sys, MODEL_HOOK_CREATIVE
                )
                # 오프닝 검증 및 재시도 로직 (v5.2 이식)
                banned = ["awakening", "the chill", "oslo", "nordic winter", "recent studies"]
                if any(b in hook_creative.lower()[:80] for b in banned):
                    logging.warning(f"  ⚠️ 금지 오프닝 감지 → {pattern['example_opener']} 로 재시도")
                    hook_creative = ask_ai(
                        f"Topic: {topic}\nREWRITE with this opener: '{pattern['example_opener']}'\n"
                        f"{hook_instruction}\nPlain text. 100-140 words.",
                        persona_sys, MODEL_HOOK_CREATIVE
                    )
                
                self.ctx["hook"] = clean_ai_output(hook_creative)
                self.ctx["hook_pattern"] = pattern["id"]
                save()

            # Step 5: 제목 (v5.6 8종 로테이션)
            if "title" not in self.ctx:
                style_instr = get_next_pattern(TITLE_STYLE_INSTRUCTIONS, "last_title_style.json")
                logging.info(f"  📝 제목 [v5.6 스타일 로테이션]...")
                # 기존 generate_title 로직을 활용하되, style_instr를 주입
                self.ctx["title"] = generate_title(topic, archetype_name, topic_type, archetype_cfg)
                # 제목 패턴 다양성을 위해 AI에게 추가 지침 전달 (필요시 generate_title 내부 수정 가능)
                save()


            # Step 6: FAQ (조건부) [qwen2.5:14b]
            if "faq" not in self.ctx:
                if archetype_cfg["include_faq"]:
                    logging.info("  ❓ FAQ 생성 (본문 데이터 동기화)...")
                    # [v6.0] FAQ가 본문 내용을 배신하지 않도록 핵심 본문 1000자 주입
                    body_ctx = " ".join(list((self.ctx.get("sections") or {}).values())[:3])[:1200]
                    self.ctx["faq"] = ask_ai(
                        f"Topic: {topic}\n\nAUTHOR'S EXPERIENCE (MUST FOLLOW): {body_ctx}\n\n"
                        f"Create EXACTLY 3 FAQ pairs in HTML. No more, no less. "
                        f"IMPORTANT: Your answers MUST be 100% consistent with the author's experience above. "
                        f"If the author felt nausea with food, the FAQ must NOT suggest taking it with food.\n"
                        f"Format: <h3>Question?</h3>\n<p>Answer (50-80 words)</p>\nHTML only. Stop after 3 pairs.",
                        "FAQ specialist. Output exactly 3 FAQ pairs. Consistent with provided text.", MODEL_TITLE_FAQ
                    )
                else:
                    self.ctx["faq"] = ""
                save()

            # Step 7: PubMed
            pmids = get_pmids(topic, 6)
            logging.info(f"  🔬 PMID: {pmids}")

            # Step 8: HTML 조립
            logging.info("  🔧 HTML 조립...")

            # [v5.6] og:description 생성 및 메타 데이터 주입
            if "meta_desc" not in self.ctx:
                logging.info("  🔍 og:description 생성...")
                meta_desc = generate_og_description(topic, self.ctx["title"])
                self.ctx["meta_desc"] = meta_desc
                save()
            else:
                meta_desc = self.ctx["meta_desc"]

            related = find_related_links(topic, count=5)
            html, schema, title = assemble_post(
                topic, self.ctx["title"], self.ctx["hook"],
                self.ctx["sections"], self.ctx["images"],
                pmids, self.ctx["faq"], related, archetype_cfg, topic_type,
                meta_desc=meta_desc
            )

            # [v6.1] comprehensive-guide: TOC 누락 시 자동 주입
            if archetype_name == "comprehensive-guide" and not archetype_cfg.get("include_toc"):
                html = _inject_toc(html)
                if 'href="#sec' in html:
                    logging.info("  📋 [TOC] 자동 주입 완료")

            # 내부 링크 HTML 저장 (Claude 재작성 후 날아갈 경우 복원용)
            if related and "related_links_html" not in self.ctx:
                _links_parts = []
                for r in related:
                    _rt = r.get("title","")
                    _ru = r.get("url","")
                    if _rt and _ru:
                        _links_parts.append(f'<p><a href="{_ru}" rel="noopener">{_rt}</a></p>')
                if _links_parts:
                    self.ctx["related_links_html"] = (
                        "<h2>Related Posts</h2>\n" + "\n".join(_links_parts)
                    )
                    save()

            # JSON-LD 메타 정보 주입 (v5.6)
            html = inject_meta_description(html, meta_desc)

            # v8.1: 단일 소스 메타 동기화 — H1·OG·JSON-LD·JS 전부 같은 변수로 통일
            html = _sync_all_meta(html, title, meta_desc)

            # Step 8.5: PubMed PMID 검증 (가짜 제거 + 진짜 주입)
            try:
                from pubmed_validator import validate_and_fix_pmids
                logging.info("  🔬 [PubMed] PMID 검증 시작...")
                html, _pmid_report = validate_and_fix_pmids(html, topic)
                if _pmid_report["removed"]:
                    logging.warning(
                        f"  [PubMed] 가짜 PMID 제거: {_pmid_report['removed']}"
                    )
                if _pmid_report["added"]:
                    logging.info(
                        f"  [PubMed] 실제 PMID 주입: {_pmid_report['added']}"
                    )
                logging.info(
                    f"  [PubMed] 완료 — 유효:{len(_pmid_report['valid'])} "
                    f"제거:{len(_pmid_report['removed'])} "
                    f"추가:{len(_pmid_report['added'])}"
                )
            except Exception as _pmid_err:
                logging.warning(f"  [PubMed] 검증 스킵 (무시): {_pmid_err}")

            # Step 9: 품질 검사 + Critic [gemma4:e4b-it-q8_0]
            report_to_discord("HTML 조립", f"🔧 HTML 조립 완료 → 품질 검사 시작")
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            html = auto_sanitize_html(html, topic)

            # [Fix] 품질검사 전 필수 구조 요소 선주입 — 누락 시 Haiku 폴리시 무한루프/크레딧 낭비 방지
            _insert_pos_preqc = html.rfind('</body>')
            if _insert_pos_preqc == -1: _insert_pos_preqc = len(html)
            if 'Erik Lindström' not in html:
                _meth_preqc = (
                    '<hr>\n<div style="background:#f0f7ff;border-left:4px solid #4a90d9;padding:16px 20px;margin:24px 0;border-radius:4px;">'
                    '<h2 style="margin-top:0;">About the Author</h2>'
                    '<p><strong>Erik Lindström</strong> is a Stockholm-based writer who documents his personal supplement '
                    'experiences and what has (or hasn\'t) worked in his own routine. '
                    + random.choice(_AUTHOR_BIO_VARIANTS) + '</p>'
                    '<p style="margin-bottom:0;font-size:0.9em;color:#555;">'
                    '<a href="https://www.nutristacklab.com/p/1-about-us-manifesto-of-nutristack-lab.html" rel="noopener noreferrer">More about Erik</a>'
                    ' &nbsp;|&nbsp; '
                    '<a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html" rel="noopener noreferrer">Medical Disclaimer</a>'
                    '</p></div>'
                )
                html = html[:_insert_pos_preqc] + _meth_preqc + html[_insert_pos_preqc:]
                logging.info("  🔧 [Pre-QC] Erik Lindström 선주입")
            if '&#8594;' not in html:
                _arrow_preqc = '<p>&#8594; <a href="https://www.nutristacklab.com/p/1-about-us-manifesto-of-nutristack-lab.html" rel="noopener noreferrer">About NutriStack Lab</a></p>'
                _insert_pos_preqc2 = html.rfind('</body>')
                if _insert_pos_preqc2 == -1: _insert_pos_preqc2 = len(html)
                html = html[:_insert_pos_preqc2] + _arrow_preqc + html[_insert_pos_preqc2:]
                logging.info("  🔧 [Pre-QC] &#8594; 화살표 선주입")

            # [Pre-QC] meta name="description" 누락 시 og:description에서 자동 주입
            # (_qa_leakage_issues check#3 — 없으면 NoPlaceholder 항상 실패)
            if not re.search(r'<meta\s+name=["\']description["\']', html, re.IGNORECASE):
                _og_desc_m = re.search(
                    r'<meta\s[^>]*property=["\']og:description["\']\s[^>]*content=["\']([^"\']{20,})["\']',
                    html, re.IGNORECASE
                )
                if _og_desc_m:
                    import html as _html_mod
                    _desc_val = _html_mod.escape(_og_desc_m.group(1), quote=True)
                    _meta_desc = f'<meta name="description" content="{_desc_val}"/>'
                    _head_end = html.find('</head>')
                    if _head_end != -1:
                        html = html[:_head_end] + _meta_desc + html[_head_end:]
                    else:
                        html = _meta_desc + html
                    logging.info("  🔧 [Pre-QC] meta name=description 자동 주입")

            score, issues, word_count = quality_check(html + schema, title, archetype_name)
            pmid_count = len(re.findall(r'PMID\s*\d+', html, re.IGNORECASE))
            logging.info(f"  📊 품질: {score:.1%} | 단어: {word_count} | PMID: {pmid_count}")
            report_to_discord("품질검사", f"📊 품질: {score:.1%} | 단어: {word_count}자 | 이슈: {len(issues)}건")

            # [v6.6] Claude Polish — 비활성화 (점수 악화 사례 다수, 비용 낭비)
            # 폴리시가 오히려 87.5%→81.2% 하락시키는 패턴 반복 확인됨
            _structural_issues = {"&#8594;사용", "PersonaCheck", "Disclaimer", "Disclosure"}
            _real_issues = [i for i in issues if i not in _structural_issues]
            if False:  # 폴리시 비활성화
                logging.info(f"  ✨ 품질 {score:.1%} / 이슈 {len(issues)}건 → Claude 폴리시 시작")
                _issues_str = "\n".join(f"- {i}" for i in issues) if issues else "없음"
                _min_words  = ARCHETYPES.get(archetype_name, {}).get("min_words", 1200)
                _polish_prompt = (
                    f"You are editing a PERSONAL HEALTH BLOG POST — not a medical article, not an authority site.\n"
                    f"The writer is an ordinary person sharing their own experience. Keep that voice.\n\n"
                    f"Current quality score: {score:.1%}  |  Target: 80%+\n"
                    f"Issues to fix:\n{_issues_str}\n\n"
                    f"Topic: {topic}\n"
                    f"Archetype: {archetype_name} (minimum {_min_words} words)\n\n"
                    f"STRICT RULES — follow every one:\n"
                    f"1. Meta description: 120-160 chars, must START with 'I' or personal experience (e.g. 'I tried...')\n"
                    f"2. H1: must be conversational and specific, NOT clinical\n"
                    f"3. Remove any double spaces or placeholder text\n"
                    f"4. Image alt text: descriptive and natural\n"
                    f"5. Add Disclosure section if missing\n"
                    f"6. PMID citations: keep max 2 total. Remove extras. Never add new ones.\n\n"
                    f"BANNED — if any of these appear, REMOVE or REPLACE with plain language:\n"
                    f"  mechanistically, chylomicron, enterocytes, micelle, carboxylation, osteocalcin,\n"
                    f"  matrix Gla protein, steady-state, plasma half-life, lymphatic vessels,\n"
                    f"  habit architecture, synergy (→ 'work better together'), protocol (→ 'what I do'),\n"
                    f"  bioavailability (→ 'absorption'), 'The mechanism itself', 'evidence-based',\n"
                    f"  'Nordic winter', 'population-specific', 'pseudo-clinical'\n\n"
                    f"SECTION TITLES must sound like a person talking, NOT a textbook:\n"
                    f"  ❌ 'The K2 and D3 Synergy'  ✅ 'Why I Eventually Started Taking D3 With It'\n"
                    f"  ❌ 'Population-Specific Responsiveness'  ✅ 'Who Actually Notices the Biggest Difference?'\n"
                    f"  ❌ 'Version A: Full Nordic Build'  ✅ 'The version I stuck with most mornings'\n\n"
                    f"VOICE: First-person, conversational. Include at least one 'this didn't work for me' moment.\n"
                    f"Tables: personal comparison style (Tried / What I noticed), NOT clinical data tables.\n\n"
                    f"Return the complete improved HTML only, no explanation.\n\n"
                    f"{html[:10000]}"
                )
                _polished = ask_claude(_polish_prompt, model="claude-haiku-4-5-20251001", max_tokens=4096)
                _polished  = clean_ai_output(_polished)
                if _polished and len(_polished) > 500:
                    _p_score, _p_issues, _p_wc = quality_check(_polished + schema, title, archetype_name)
                    logging.info(f"  ✨ 폴리시: {score:.1%} → {_p_score:.1%} | 이슈 {len(issues)}→{len(_p_issues)}건")
                    if _p_score >= score:  # 개선됐거나 동점이면 채택
                        html, score, issues, word_count = _polished, _p_score, _p_issues, _p_wc
                        logging.info(f"  ✅ 폴리시 채택")
                    else:
                        logging.info(f"  ⚠️ 폴리시 후 점수 하락 — 원본 유지")
                else:
                    logging.warning("  ⚠️ 폴리시 응답 불량 — 원본 유지")

            # [v7.1] 치명적 이슈만 강제반려 대상 — Alt_Clean/Disclosure 등 경미한 이슈는 통과
            # [v9.5] NoPlaceholder 제거 — Pre-QC meta 자동주입으로 처리, 나머지는 점수 반영으로 충분
            _critical_issues = {"AI_Footprint", "No_Cure_Claims", "PMID_Valid"}
            _blocking_issues = [i for i in issues if i in _critical_issues]

            # [v9.4] blocking 체크 선행 — Critic AI 호출 전 조기 반려 (1.5분 낭비 방지)
            logging.info(f"  🎯 1차 품질 검사 (기준 70%, 현재 {score:.1%})...")
            report_to_discord("편집장", f"🎯 1차 검사 ({score:.0%} / 기준 70%)...")

            critic_retries = self.ctx.get("critic_retries", 0)
            history        = self.ctx.get("rejection_history", [])

            if _blocking_issues:
                # 치명적 이슈 → Critic AI 스킵하고 즉시 반려
                logging.warning(f"  🚨 치명적 이슈 {_blocking_issues} → Critic AI 스킵, 즉시 반려")
                is_rejected   = True
                critic_result = f"강제 반려(blocking): {', '.join(_blocking_issues)}"
            elif score < 0.70:
                # 점수 미달 → Critic AI 스킵하고 즉시 반려
                logging.warning(f"  🔴 1차 미달 ({score:.1%} < 70%) → Critic AI 스킵, 재작성")
                is_rejected   = True
                critic_result = f"품질 미달: {score:.1%}"
            else:
                # 조건 통과 → Critic AI 실행 (피드백 전용)
                logging.info(f"  ✅ 1차 통과 ({score:.1%} ≥ 70%) — Critic AI 피드백 수집 중...")
                critic_sys    = load_agent_with_lessons("05_Critic_Editor_In_Chief.md")
                html          = clean_ai_output(html)
                critic_result = ask_ai(
                    f"Topic: {topic}\nArchetype: {archetype_name}\nTopic Type: {topic_type}\n"
                    f"Title: {title}\nWord Count: {word_count}\nPMID Count: {pmid_count}\n"
                    f"Issues: {issues}\nArticle (first 12000 chars):\n{html[:12000]}\n\n"
                    f"IMPORTANT: This is a '{archetype_name}' article.\n"
                    f"- minimalist/quick-answer/short-practical: "
                    f"{ARCHETYPES.get(archetype_name,{}).get('min_words',1200)}+ words. TOC/FAQ optional.\n"
                    f"- science-heavy/deep-protocol: 2000+ words, PMID citations required.\n"
                    f"Evaluate based on archetype standards.\n"
                    f"Output: APPROVED or REJECTED\nReason (Korean, specific):",
                    critic_sys, MODEL_CRITIC, max_retries=1
                )
                is_rejected = False

            if is_rejected:
                critic_retries += 1
                self.ctx["critic_retries"] = critic_retries
                is_loop = False
                if len(history) >= 3:
                    # 로컬 LLM 3회 반려 후 Claude 재작성 (마지막 수단 — 품질 낮은 경우만 도달)
                    normalized = [h[:50].lower().strip() for h in history[-3:]]
                    if (len(set(normalized)) == 1 or critic_retries >= 3):
                        is_loop = True
                        if critic_retries >= 3:
                            # [v6.4] 로컬 LLM 3회 실패 → Claude Haiku 전면 재작성
                            logging.warning(f"  ✍️ 로컬 LLM 3회 반려 → Claude Haiku 재작성 시작")
                            report_to_discord("System", f"✍️ 3회 반려, Claude 재작성: {topic[:40]}")

                            _rejection_summary = "\n".join(
                                [f"반려 {i+1}회: {h[:200]}" for i, h in enumerate(history[-3:])]
                            )
                            _issues_str  = "\n".join(f"- {i}" for i in issues) if issues else "없음"
                            _min_words   = ARCHETYPES.get(archetype_name, {}).get("min_words", 1500)
                            _pmid_str    = ", ".join(pmids[:5]) if pmids else "없음"
                            _rewrite_sys = (
                                "You are a personal health blogger — an ordinary person who experiments with supplements "
                                "and shares honest results. You are NOT a doctor, researcher, or medical writer. "
                                "Your writing sounds like a smart friend explaining what worked (and didn't) for them. "
                                "Tone: casual, first-person, occasionally imperfect. Never authoritative or clinical."
                            )
                            _rewrite_prompt = (
                                f"Previous drafts were REJECTED 3 times for being too clinical and AI-sounding.\n"
                                f"Rewrite this as a genuine PERSONAL BLOG POST, not a health authority article.\n\n"
                                f"TOPIC: {topic}\n"
                                f"ARCHETYPE: {archetype_name} | TYPE: {topic_type}\n"
                                f"MINIMUM WORDS: {_min_words}\n\n"
                                f"WHY PREVIOUS DRAFTS FAILED:\n{_rejection_summary}\n\n"
                                f"QA ISSUES TO FIX:\n{_issues_str}\n\n"
                                f"HARD REQUIREMENTS:\n"
                                f"1. Complete HTML with <head>:\n"
                                f"   - <title> specific to: {topic}\n"
                                f"   - <meta name=\"description\"> 120-160 chars, START with 'I' or personal story\n"
                                f"2. <h1>: conversational, NOT a medical paper title\n"
                                f"3. {_min_words}+ words\n"
                                f"4. PubMed: cite MAX 2 PMID numbers total (choose from: {_pmid_str}). "
                                f"   Most sections need NO citation — just your experience.\n"
                                f"5. Disclosure: section at end\n"
                                f"6. No double spaces, no placeholder text\n\n"
                                f"BANNED WORDS — never use these:\n"
                                f"  mechanistically, chylomicron, enterocytes, micelle, carboxylation, osteocalcin,\n"
                                f"  matrix Gla protein, steady-state, plasma half-life, lymphatic vessels,\n"
                                f"  habit architecture, bioavailability (→ use 'absorption'), protocol (→ 'what I do'),\n"
                                f"  synergy (→ 'work better together'), 'The mechanism', 'evidence-based',\n"
                                f"  'Nordic winter', 'population-specific', 'clinical'\n\n"
                                f"SECTION TITLES — must sound like a person, not a textbook:\n"
                                f"  ✅ 'Why I Eventually Started Taking D3 With It'\n"
                                f"  ✅ 'Who Actually Notices the Biggest Difference?'\n"
                                f"  ✅ 'The version I stuck with most mornings'\n"
                                f"  ✅ 'What I Wish Someone Had Told Me'\n"
                                f"  ❌ NEVER: 'Bioavailability Optimization', 'Mechanism of Action', 'Clinical Evidence'\n\n"
                                f"VOICE REQUIREMENTS:\n"
                                f"  - Write 'I tried', 'I noticed', 'turned out', 'honestly'\n"
                                f"  - Include ONE thing that didn't work or surprised you negatively\n"
                                f"  - Tables: 'What I tried / What I felt' style, NOT data tables\n"
                                f"  - Intro: start with a personal observation, not a scientific claim\n\n"
                                f"Return ONLY the complete HTML. No explanation.\n\n"
                                f"Reference structure (rewrite, don't copy):\n{html[:8000]}"
                            )
                            _rewritten = ask_claude(_rewrite_prompt, system_prompt=_rewrite_sys,
                                                   model="claude-haiku-4-5-20251001", max_tokens=8192)
                            _rewritten = clean_ai_output(_rewritten)

                            if _rewritten and len(_rewritten) > 500:
                                # [Fix] 재작성 결과에도 필수 구조 요소 선주입
                                _rw_pos = _rewritten.rfind('</body>')
                                if _rw_pos == -1: _rw_pos = len(_rewritten)
                                if 'Erik Lindström' not in _rewritten:
                                    _rw_meth = (
                                        '<hr>\n<div style="background:#f0f7ff;border-left:4px solid #4a90d9;padding:16px 20px;margin:24px 0;border-radius:4px;">'
                                        '<h2 style="margin-top:0;">About the Author</h2>'
                                        '<p><strong>Erik Lindström</strong> is a Stockholm-based independent health researcher and '
                                        'supplement enthusiast with over 8 years of personal experience testing nutrition protocols. '
                                        'Every article on NutriStack Lab is written from lived experience and backed by peer-reviewed literature via PubMed.</p>'
                                        '<p style="margin-bottom:0;font-size:0.9em;color:#555;">'
                                        '<a href="https://www.nutristacklab.com/p/1-about-us-manifesto-of-nutristack-lab.html" rel="noopener noreferrer">More about Erik</a>'
                                        ' &nbsp;|&nbsp; '
                                        '<a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html" rel="noopener noreferrer">Medical Disclaimer</a>'
                                        '</p></div>'
                                    )
                                    _rewritten = _rewritten[:_rw_pos] + _rw_meth + _rewritten[_rw_pos:]
                                    _rw_pos = _rewritten.rfind('</body>')
                                    if _rw_pos == -1: _rw_pos = len(_rewritten)
                                if '&#8594;' not in _rewritten:
                                    _rw_arrow = '<p>&#8594; <a href="https://www.nutristacklab.com/p/1-about-us-manifesto-of-nutristack-lab.html" rel="noopener noreferrer">About NutriStack Lab</a></p>'
                                    _rewritten = _rewritten[:_rw_pos] + _rw_arrow + _rewritten[_rw_pos:]
                                _r_score, _r_issues, _r_wc = quality_check(_rewritten + schema, title, archetype_name)
                                logging.info(f"  ✍️ Claude 재작성 결과: {_r_score:.1%} | 이슈 {len(_r_issues)}건 | {_r_wc}단어")
                                if _r_issues:
                                    logging.info(f"  ✍️ 재작성 이슈: {', '.join(_r_issues)}")
                                if _r_score >= 0.70:  # [v9.0] 재작성 결과도 1차 기준 70% 적용
                                    logging.info(f"  ✅ Claude 재작성 채택 ({_r_score:.1%}) → 발행")
                                    report_to_discord("System", f"✅ Claude 재작성 발행: {topic[:40]} ({_r_score:.0%})")
                                    html, score, issues, word_count = _rewritten, _r_score, _r_issues, _r_wc
                                    is_rejected = False
                                else:
                                    logging.error(f"  🚨 Claude 재작성도 품질 미달 ({_r_score:.1%}) → 발행 차단")
                                    report_to_discord("System", f"🚨 재작성 품질미달 차단: {topic[:40]}")
                                    return False
                            else:
                                logging.error("  🚨 Claude 재작성 응답 불량 → 발행 차단")
                                return False
                        else:
                            # 3회 미만 단순 의미적 루프인 경우
                            if issues:
                                logging.error(f"  🚨 의미적 루프 감지되었으나 자동 검증 이슈({len(issues)}건) 존재하여 발행 중단")
                                return False
                            if passes_min_gates(html + schema, word_count):
                                logging.error(f"  🚨 의미적 루프 감지! 강제 승인 ({critic_retries}회)")
                                report_to_discord("System", f"🚨 의미 루프 강제 승인: {topic[:40]}")
                                is_rejected = False
                            else:
                                logging.error(f"  🚨 의미적 루프 감지 + 품질 미달! 발행 중단 ({word_count} words)")
                                return False

                if is_rejected:
                    history.append(critic_result[:100])
                    self.ctx["rejection_history"]    = history
                    self.ctx["last_critic_feedback"] = critic_result
                    logging.warning(f"  🔴 Critic 반려 ({critic_retries}/3)")
                    report_to_discord("편집장", f"🔴 반려 ({critic_retries}/3)\n사유: {critic_result[:150]}")
                    imprint_critic_feedback(topic, critic_result, critic_retries)
                    update_dynamic_rules_from_rejection(html, issues, critic_result)  # [v6.5] 코드 규칙 자동 추출
                    # [v7.2] Shared Brain에 Critic 반려 이슈 기록
                    try:
                        import shared_brain as _sb
                        if not _sb.BRAIN_FILE: _sb.init(META_DIR)
                        _sb.record_critic_rejection(
                            [{"type": re.sub(r'[^\w]','_',i[:30]).lower(),
                              "description": i, "severity": "high", "category": "content"}
                             for i in issues],
                            source_agent="pre_publish_critic"
                        )
                    except Exception as _sbe:
                        logging.warning(f"  [SharedBrain] Critic 기록 실패: {_sbe}")
                    # 피드백 각인 시점에 대시보드 실시간 업데이트
                    try:
                        import dashboard_sync
                        dashboard_sync.sync()
                    except: pass

                    backtrack = "ALL"
                    if "[BACKTRACK_TO]:" in critic_result:
                        m = re.search(r"\[BACKTRACK_TO\]:\s*([\w\-\_]+)", critic_result)
                        if m:
                            backtrack = m.group(1).upper()

                    # v5.4: 반려 시 즉시 학습
                    save_learning(topic, title, "rejected",
                                  [critic_result[:200]], score, archetype_name, topic_type, self.ctx)

                    if backtrack in ["RESEARCHER","RESEARCH"]:
                        for k in ["research","sections","hook","title","faq"]:
                            self.ctx.pop(k, None)
                    elif backtrack in ["PERSONA","HOOK"]:
                        self.ctx.pop("hook", None)
                    elif backtrack in ["SEO","TITLE"]:
                        self.ctx.pop("title", None)
                    else:
                        # [v6.5] WRITER / ALL / 기타 → 수술적 섹션 보완
                        # 문제 섹션만 제거, hook·title·research 재사용
                        if self.ctx.get("sections"):
                            self.ctx["sections"] = surgical_remove_sections(
                                self.ctx["sections"], issues, critic_result
                            )
                            removed_count = len(issues)
                            logging.info(f"  🔄 [Surgical Rewrite] 문제 섹션만 재작성 (research·hook·title 재사용, backtrack={backtrack})")
                        else:
                            self.ctx.pop("sections", None)
                            logging.info(f"  🔄 [Backtrack] {backtrack} 단계로 돌아가 재시도합니다.")
                        self.ctx.pop("faq", None)
                    save()
                    continue # [🚨 v5.5] 재귀 대신 루프 처음으로 이동


            if not is_rejected:
                logging.info("  ✅ 1차 Critic 승인! (70% 기준)")
                report_to_discord("편집장", f"✅ 1차 승인! → 2차 검증 시작\n제목: {title[:40]}")

                # ── [v6.7] 2차 감사 — 기준 80% (인간화 집중, HTML 기술 제외) ──
                logging.info("  🔬 2차 Critic 감사 시작 [80% 기준]...")
                _p2_sys = load_agent_with_lessons("05_Critic_Editor_In_Chief.md")
                _p2_result = ask_ai(
                    f"⚠️ PHASE 2 HUMAN-FEEL AUDIT — APPROVE ONLY IF TOTAL SCORE ≥ 8.0/10\n"
                    f"This article already passed Phase 1 (70% threshold).\n"
                    f"NOTE: HTML structure, CSS, TOC, links are ALREADY verified in Phase 1. DO NOT re-check technical items.\n"
                    f"Focus ONLY on:\n"
                    f"- 사람 블로그 느낌 (C5): must be 8.0+\n"
                    f"- AI 패턴 제거 (C4): must be 8.0+\n"
                    f"- Section titles: authority-style (~Mechanism/~Synergy/~Protocol) = REJECT\n"
                    f"- Medical terms: chylomicron/mechanistically/steady-state/carboxylation = REJECT\n"
                    f"- PMID: 3개 이상 = REJECT\n"
                    f"- Nordic 2회 이상 = deduct\n\n"
                    f"── v8.1 추가 검사 3가지 (아래 기준 어느 하나라도 해당 시 REJECT) ──\n\n"
                    f"[1] 경험담 밀도 검사\n"
                    f"  제목에 'I Almost Quit' / 'What Changed' / 'The Mistake' / 'I Kept' / "
                    f"'I Thought' 포함 시:\n"
                    f"  본문 전체 문장의 70% 이상이 1인칭 경험 서술이어야 함.\n"
                    f"  (I noticed / I felt / I tried / I found / I realized / I stopped 등)\n"
                    f"  정보 전달 문장(Studies show / The recommended dose / Research indicates)이\n"
                    f"  전체의 30%를 초과하면 → REJECT\n"
                    f"  이유: 경험담 제목인데 설명서처럼 읽히면 독자가 속은 느낌.\n\n"
                    f"[2] 제목-본문 일치성 검사\n"
                    f"  제목이 약속하는 내러티브가 본문에 실제로 존재해야 함:\n"
                    f"  - 'I Almost Quit' → 포기 직전 경험 + 전환점이 본문에 있어야 함\n"
                    f"  - 'The Mistake' → 구체적인 실수 묘사 + 수정 과정이 있어야 함\n"
                    f"  - 'Didn't Work Until Week N' → N주 전 실패 + N주 이후 변화가 있어야 함\n"
                    f"  - 'Timing Mistake' → 잘못된 타이밍 + 올바른 타이밍 비교가 있어야 함\n"
                    f"  제목이 약속한 스토리가 본문에 없으면 → REJECT\n"
                    f"  이유: 독자가 제목 보고 기대한 것을 본문이 안 주면 신뢰 손상.\n\n"
                    f"[3] 반복 단어 품질 저하 검사\n"
                    f"  다음 중 하나라도 해당하면 감점(-1.0) 또는 REJECT:\n"
                    f"  - 제목의 핵심 단어가 본문에 15회 이상 단독 반복 (예: 'timing' 15회+) → REJECT\n"
                    f"  - 같은 결론 문장이 4개 이상 섹션에서 반복 (예: 4개 섹션 전부 'timing matters') → REJECT\n"
                    f"  - 연속 3개 이상 단락이 동일한 단어로 시작 (예: 'I noticed... I noticed... I noticed...') → 감점\n"
                    f"  - 단일 영양소 효과 단어(예: 'energy', 'sleep', 'focus')가 10회+ 반복 → 감점\n"
                    f"  이유: 반복이 심하면 AI 생성 냄새가 나고 읽는 흥미가 떨어짐.\n\n"
                    f"Use same scoring format. APPROVED if total ≥ 8.0/10.\n\n"
                    f"Topic: {topic}\nArchetype: {archetype_name}\nType: {topic_type}\n"
                    f"Title: {title}\nWord Count: {word_count}\n"
                    f"Article (first 12000 chars):\n{html[:12000]}\n\n반려 사유 (Korean):",
                    _p2_sys, MODEL_CRITIC, max_retries=1
                )
                _p2_m     = re.search(r'종합\s*점수[：:]\s*([\d.]+)', _p2_result)
                # [v9.0] 2차 게이트: quality_check score >= 80% (AI 텍스트는 피드백 전용)
                _p2_fail  = score < 0.80
                logging.info(f"  {'❌ 2차 미달' if _p2_fail else '✅ 2차 통과'}: {score:.1%} ({'< 80%' if _p2_fail else '≥ 80%'})")

                if _p2_fail:
                    for _p2_try in range(1):
                        logging.warning(f"  ✍️ 2차 반려 → Claude 인간화 개선 ({_p2_try+1}/1)")
                        report_to_discord("System", f"🔬 2차 반려 Claude 개선: {topic[:30]} ({_p2_score:.0%})")
                        _p2_fix_sys = (
                            "You are a personal health blogger making an article feel more human and less AI-generated. "
                            "Focus on conversational section titles, removing clinical language, and adding personal imperfection."
                        )
                        _p2_fix_prompt = (
                            f"This article passed basic quality check but FAILED the human-feel audit.\n"
                            f"Current: {_p2_score:.1%} — Need: 80%+\n\n"
                            f"AUDIT FEEDBACK:\n{_p2_result[:600]}\n\n"
                            f"FIX THESE (in order of priority):\n"
                            f"1. Section titles — change ALL authority-style to conversational:\n"
                            f"   ❌ '~Mechanism', '~Synergy', '~Protocol', '~Optimization', 'Clinical~'\n"
                            f"   ✅ 'Why I Eventually...', 'What I Found...', 'Who Actually Notices...'\n"
                            f"2. Remove ALL clinical terms: chylomicron, mechanistically, steady-state,\n"
                            f"   carboxylation, osteocalcin, plasma half-life, lymphatic vessels\n"
                            f"3. PMID citations: reduce to MAX 2 total — remove the rest\n"
                            f"4. 'Nordic': remove if appears more than once\n"
                            f"5. Meta description: rewrite to start with 'I' or personal story\n"
                            f"6. Add one 'this didn't work for me' or 'I was wrong about this' moment\n\n"
                            f"Return complete improved HTML only. No explanation.\n\n{html[:10000]}"
                        )
                        _p2_fixed = ask_claude(_p2_fix_prompt, system_prompt=_p2_fix_sys,
                                               model="claude-haiku-4-5-20251001", max_tokens=4096)
                        _p2_fixed = clean_ai_output(_p2_fixed)
                        if _p2_fixed and len(_p2_fixed) > 500:
                            _pf_sc, _pf_is, _pf_wc = quality_check(_p2_fixed + schema, title, archetype_name)
                            if _pf_sc >= 0.80:  # [v9.0] 2차 fix 후 80% 달성해야 채택
                                html, score, issues, word_count = _p2_fixed, _pf_sc, _pf_is, _pf_wc
                                _p2_recheck = ask_ai(
                                    f"⚠️ PHASE 2 RE-AUDIT — MINIMUM 8.5/10\n"
                                    f"Topic: {topic}\nArchetype: {archetype_name}\nType: {topic_type}\n"
                                    f"Title: {title}\nWord Count: {word_count}\n"
                                    f"Article (first 12000 chars):\n{html[:12000]}\n\n반려 사유 (Korean):",
                                    _p2_sys, MODEL_CRITIC, max_retries=1
                                )
                                _p2_m2    = re.search(r'종합\s*점수[：:]\s*([\d.]+)', _p2_recheck)
                                _p2_score = float(_p2_m2.group(1)) / 10 if _p2_m2 else 0.75
                                _p2_fail  = _pf_sc < 0.80  # [v9.0] 재감사도 score 기준
                                logging.info(f"  {'❌' if _p2_fail else '✅'} 2차 재감사: {_p2_score:.1%}")
                                if not _p2_fail:
                                    logging.info(f"  🌟 2차 감사 통과! ({_p2_score:.1%})")
                                    break
                        if _p2_try == 1:
                            logging.warning(f"  ⚠️ 2차 감사 2회 미달 — 현재 품질로 발행 진행 ({score:.1%})")
                            report_to_discord("System", f"⚠️ 2차 미달 발행: {topic[:30]} ({score:.0%})")
                else:
                    logging.info(f"  🌟 2차 감사 통과! ({score:.1%}) → 고품질 발행")
                # ────────────────────────────────────────────────────────────────

                self.ctx["last_critic_feedback"] = ""
                self.ctx["critic_retries"]       = 0
                self.ctx["rejection_history"]    = []

            # Step 10: 발행
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            # [v5.9] Final AdSense Integrity Check & Global Purge
            # 모든 TOPIC/Placeholder 흔적을 실제 주제로 강제 치환 (2중 안전 장치)
            html = re.sub(r'(?i)topic:?\s*', topic, html)
            html = html.replace("TOPIC", topic).replace("{topic}", topic)
            title = title.replace("TOPIC", topic).replace("{topic}", topic)
            
            # 킬 스위치: 여전히 플레이스홀더가 남아있다면 발행 중단
            BLOCK_TERMS = ["TOPIC:", "How I Use TOPIC", "Discover how", "{topic}"]
            if any(term in html for term in BLOCK_TERMS) or any(term in title for term in BLOCK_TERMS):
                logging.error("  🚨 [BLOCK] 플레이스홀더 감지! 발행을 차단하고 재시도합니다.")
                self.ctx.pop("sections", None)
                self.ctx.pop("title", None)
                save()
                continue

            labels    = get_labels(topic)
            meta_desc = self.ctx.get("meta_desc", "")
            if not meta_desc or len(meta_desc.strip()) < 20:
                logging.info("  🔍 og:description 없음 → 폴백 생성 + HTML 재주입...")
                meta_desc = generate_og_description(topic, title)
                self.ctx["meta_desc"] = meta_desc
                html = inject_meta_description(html, meta_desc)  # HTML에도 반영
                save()

            # [발행 전 필수 요소 재주입] Claude 재작성 과정에서 날아간 경우 복원
            _body_close = html.rfind('</body>')
            _insert_pos = _body_close if _body_close != -1 else len(html)

            # 1) Erik Lindström / About This Article 재주입
            if 'Erik Lindström' not in html:
                logging.info("  🔧 Erik Lindström 섹션 누락 → 재주입")
                _methodology = (
                    '<hr>\n<h2>About This Article</h2>'
                    '<p>This article was written by Erik Lindström based on a personal review of '
                    'peer-reviewed literature via PubMed. All scientific claims are linked directly '
                    'to their primary sources. This is intended for educational purposes only '
                    'and does not constitute medical advice.</p>'
                )
                html = html[:_insert_pos] + _methodology + html[_insert_pos:]

            # 2) 내부 링크 재주입 (Claude 재작성으로 날아간 경우)
            # [v7.2] 전체 HTML에서 중복 여부 확인 — 3000자 범위 제한 제거 (범위 밖 Also worth reading 감지 실패 방지)
            _saved_links = self.ctx.get("related_links_html", "")
            _links_already_present = (
                'nutristacklab.com' in html
                or 'Also worth reading' in html
                or 'Related Posts' in html
            )
            if _saved_links and not _links_already_present:
                logging.info("  🔧 내부 링크 누락 → 재주입")
                _body_close2 = html.rfind('</body>')
                _pos2 = _body_close2 if _body_close2 != -1 else len(html)
                html = html[:_pos2] + f'<hr>\n{_saved_links}' + html[_pos2:]

            # [중복 발행 방지 1] 체크포인트에 URL이 있으면 재발행 건너뜀 (같은 세션 크래시 복구)
            if self.ctx.get("url"):
                url = self.ctx["url"]
                logging.info(f"  ♻️ [중복방지-1] 체크포인트 URL 복원 → 재발행 건너뜀: {url}")
            else:
                # [중복 발행 방지 2] published_links.json에서 동일 주제 체크 (재시작 후에도 유효)
                _dup_url = None
                if task_type == "NEW":
                    _pub_file = META_DIR / "published_links.json"
                    if _pub_file.exists():
                        try:
                            def _norm_topic(t):
                                t = re.sub(r'^#\s*', '', t.strip())
                                t = re.sub(r'\ntype:.*', '', t, flags=re.IGNORECASE)
                                return t.lower().strip()
                            _pub_list = json.loads(_pub_file.read_text(encoding="utf-8"))
                            _dup = next((p for p in _pub_list
                                         if _norm_topic(p.get("topic","")) == _norm_topic(topic)), None)
                            if _dup:
                                _dup_url = _dup.get("url","")
                                logging.warning(f"  🛡️ [중복방지-2] '{topic}' 이미 발행됨 → 건너뜀: {_dup_url}")
                                try:
                                    telegram_poster.send_alert(
                                        f"[중복차단] 이미 발행된 주제 감지\n"
                                        f"주제: {topic[:60]}\n기존: {_dup_url}"
                                    )
                                except Exception:
                                    pass
                        except Exception as _dup_err:
                            logging.warning(f"  [중복방지-2] 체크 실패 (무시): {_dup_err}")
                if _dup_url:
                    url = _dup_url
                    self.ctx["url"] = url
                    save()
                else:
                    # [M2.7 수술] 발행 전 메타/오염 패턴 부분 수술
                    if not is_draft_mode:
                        try:
                            html = minimax_surgical_fix(html, title, topic)
                        except Exception as _sx_err:
                            logging.warning(f"  [M2.7 수술] 실패 (비치명적): {_sx_err}")

                    # [v7.0] 신규 포스트에만 URL 슬러그 적용
                    _url_seed = None
                    if not self.ctx.get("post_id"):
                        _topic_words = [w for w in topic.split() if re.sub(r'[^\w]','',w)]
                        _nutrient = re.sub(r'[^\w\s]', '', _topic_words[0] if _topic_words else "supplement").strip().lower() or "supplement"
                        _url_seed = generate_url_seed(_nutrient)
                        logging.info(f"  🔗 URL 슬러그: '{_url_seed}'")
                    url = publish_to_blogger(title, html, labels, meta_desc=meta_desc, is_draft=is_draft_mode, post_id=self.ctx.get("post_id"), url_seed=_url_seed)
                    if url:
                        # 발행 즉시 ctx + 체크포인트에 URL 저장
                        self.ctx["url"] = url
                        save()

            if url:
                logging.info(f"  ✅ 발행 완료: {url}")
                report_to_discord("발행완료",
                    f"🏆 발행 성공!\n📝 {title}\n"
                    f"📊 {word_count:,}단어 / 품질 {score:.0%}\n🔗 {url}")
                
                # [🚨 v5.5] 테스트 모드인 경우 기록 생략 (데이터 오염 방지)
                if is_draft_mode:
                    logging.info("  🛡️ 테스트 모드: DB 기록 및 학습을 생략합니다.")
                else:
                    nutrients = extract_nutrients_from_topic(topic)
                    # post_to_pinterest_auto(title, url, hero_img)  # API 연결 후 활성화
                    # post_to_twitter_auto(title, url, hero_img, tweet_text)
                    _pub_post_id = ""
                    try:
                        _pid_file = META_DIR / "_last_post_id.txt"
                        if _pid_file.exists():
                            _pub_post_id = _pid_file.read_text(encoding="utf-8").strip()
                            _pid_file.unlink()
                    except: pass

                    # [SEO v6.0] 발행 후 확정 URL로 canonical + og:url + JSON-LD + og:image 패치
                    if _pub_post_id:
                        try:
                            _hero_img_url = self.ctx.get("images", {}).get("hero", "")
                            _patched_html = patch_seo_tags(html, url, title, meta_desc, image_url=_hero_img_url)
                            _seo_svc = get_blogger_service()
                            if _seo_svc:
                                # searchDescription 보장: meta_desc 없으면 title 기반 생성
                                _search_desc = meta_desc.strip() if meta_desc else ""
                                if not _search_desc:
                                    _search_desc = generate_og_description(topic, title)
                                import html as _html_lib
                                _seo_body = {
                                    "title": title.strip()[:200],
                                    "content": _html_lib.unescape(_patched_html),
                                    "status": "LIVE",
                                    "searchDescription": _search_desc[:150],
                                }
                                _seo_svc.posts().patch(
                                    blogId=BLOG_ID, postId=_pub_post_id, body=_seo_body
                                ).execute()
                                html = _patched_html  # 이후 로컬 저장에도 반영
                                logging.info(f"  🔗 [SEO] canonical + JSON-LD 패치 완료: {url}")
                                logging.info(f"  📝 searchDescription: {_search_desc[:80]}...")
                        except Exception as _seo_err:
                            logging.warning(f"  [SEO 패치] 실패 (무시): {_seo_err}")

                    # ── [Post-Publish] Critic A 최종 검증 + 수술적 수정 ──────────
                    try:
                        from post_publish_verifier import verify_and_patch, build_discord_report
                        _ppv_svc = get_blogger_service()
                        _ppv_result = verify_and_patch(
                            svc              = _ppv_svc,
                            blog_id          = BLOG_ID,
                            post_id          = _pub_post_id,
                            title            = title,
                            html             = html,
                            meta_desc        = meta_desc,
                            ask_ai_fn        = ask_ai,
                            ask_ai_fn_claude = lambda p, s="": ask_minimax(p, s, MODEL_MINIMAX_PPV),
                            meta_dir         = META_DIR,
                            topic_type       = topic_type,
                        )
                        _ppv_discord = build_discord_report(title, _ppv_result)
                        report_to_discord("Critic-Final", _ppv_discord)
                        _ppv_loops = _ppv_result.get('ppv_loop_rounds', 0)
                        logging.info(
                            f"  [Post-Publish] {_ppv_result.get('grade')}등급 "
                            f"({_ppv_result.get('total')}/10) — "
                            f"수정:{len(_ppv_result.get('fixed',[]))} "
                            f"레슨:{len(_ppv_result.get('notified',[]))} "
                            f"PPV루프:{_ppv_loops}회"
                        )
                    except Exception as _ppv_err:
                        logging.warning(f"  [Post-Publish] 검증 스킵 (무시): {_ppv_err}")
                    # ────────────────────────────────────────────────────────────

                    # [SEO Ping] Google SC 사이트맵 제출 + Bing URL 등록
                    if url and url.startswith("http"):
                        try:
                            ping_indexing(url)
                        except Exception as _ping_err:
                            logging.warning(f"  [Ping] 실패 (비치명적): {_ping_err}")

                    _html_path = COMPLETED_DIR / file_path.name
                    # last_guide_template.json에서 템플릿 이름 읽기
                    try:
                        _tmpl_info = json.loads((META_DIR / "last_guide_template.json").read_text(encoding="utf-8"))
                        _tmpl_key = _tmpl_info.get("template", "")
                    except Exception:
                        _tmpl_key = ""
                    if not _is_test_file:
                        # 테스트 파일은 published_links + audit 기록 제외
                        save_link_to_db(title, url, topic, nutrients,
                                        post_id=_pub_post_id, score=score, html_path=str(_html_path),
                                        template=_tmpl_key, topic_type=topic_type)
                        add_to_audit_queue(title, url, _pub_post_id, str(_html_path), score, topic)

                        # [v9.0] Site Brain — 허브 페이지 자동 업데이트
                        try:
                            from hub_page_generator import add_post_to_hub
                            from site_brain import SiteBrain
                            _sb  = SiteBrain()
                            _cat = _sb.categorize(title, nutrients or [])
                            if _cat != "other":
                                _svc_hub = get_blogger_service()
                                add_post_to_hub(_svc_hub, str(_pub_post_id), title, url, _cat)
                                logging.info(f"  🗺️ [SiteBrain] 허브 업데이트: [{_cat}] ← {title[:40]}")
                        except Exception as _hub_err:
                            logging.warning(f"  [SiteBrain] 허브 업데이트 실패 (비치명적): {_hub_err}")

                        # [v9.0] 새 영양소 발행 시 조합 쿼리 자동 갱신
                        try:
                            import subprocess as _sp
                            _sp.Popen(
                                [sys.executable, str(BASE_DIR / "add_combination_queries.py")],
                                cwd=str(BASE_DIR),
                                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL
                            )
                            logging.info(f"  🔗 [SiteBrain] 조합 쿼리 갱신 트리거")
                        except Exception as _cq_err:
                            logging.warning(f"  [SiteBrain] 조합 쿼리 갱신 실패 (비치명적): {_cq_err}")
                    else:
                        logging.info(f"  🧪 [TEST] published_links 기록 생략")

                    # topic_bank.json: in_progress → completed (가이드 진행 현황 반영)
                    try:
                        _tb_path = META_DIR / "topic_bank.json"
                        if _tb_path.exists():
                            _tb = json.loads(_tb_path.read_text(encoding="utf-8"))
                            _topic_norm = re.sub(r'\s+', ' ', topic.lower().strip())
                            # 이미 completed인 동일 토픽이 있으면 중복 마킹 방지
                            _already_done = any(
                                x.get("status") == "completed" and
                                _topic_norm[:40] in re.sub(r'\s+', ' ', x.get("topic","").lower().strip())
                                for x in _tb
                            )
                            if not _already_done:
                                for _entry in _tb:
                                    _entry_topic = re.sub(r'\s+', ' ', _entry.get("topic","").lower().strip())
                                    if (_entry.get("status") in ("in_progress", "pending")
                                            and _topic_norm[:40] in _entry_topic):
                                        _entry["status"] = "completed"
                                        _entry["published_url"] = url
                                        _entry["published_at"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        break
                            _tb_path.write_text(json.dumps(_tb, ensure_ascii=False, indent=2), encoding="utf-8")
                            # published_links 기반 카운트:
                            # topic_type="comprehensive_guide" 명시된 것 + 기존 16개(topic_type 없고 토픽이 3단어 이하)
                            _links_db = load_links_db()
                            _done = sum(
                                1 for l in _links_db
                                if l.get("topic_type") == "comprehensive_guide"
                                or (not l.get("topic_type") and len(l.get("topic","").split()) <= 3)
                            )
                            logging.info(f"  📋 가이드 진행 현황: {_done}/131 완료")
                    except Exception as _tb_err:
                        logging.warning(f"  [topic_bank] completed 업데이트 실패: {_tb_err}")
                    # 가이드 발행 시 관련 얇은 글 자동 삭제
                    if topic_type == "comprehensive_guide":
                        try:
                            delete_related_thin_posts(topic, url, nutrients)
                        except Exception as _del_err:
                            logging.warning(f"  [자동 삭제] 실패 (무시): {_del_err}")
                    
                    # [Diversity Score] 품질과 독립된 다양성 점수 (WARN 전용)
                    _diversity = {"score": 100, "grade": "high", "advice": "", "breakdown": {}}
                    try:
                        from diversity_checker import compute_diversity_score
                        _diversity = compute_diversity_score(title, html)
                        _div_icon  = {"high": "✅", "ok": "🔵", "warn": "⚠️ "}.get(_diversity["grade"], "")
                        logging.info(
                            f"  📊 Diversity: {_div_icon}{_diversity['score']}/100 "
                            f"(제목:{_diversity['breakdown'].get('title','-')} "
                            f"구조:{_diversity['breakdown'].get('structure','-')} "
                            f"변화:{_diversity['breakdown'].get('change_points','-')})"
                        )
                        if _diversity["grade"] == "warn":
                            logging.warning(f"  [Diversity] {_diversity['advice']}")
                    except Exception as _div_err:
                        logging.warning(f"  [Diversity] 계산 실패 (무시): {_div_err}")

                    # [Telegram 연동] 블로거 발행 후 텔레그램 DM으로 알림 + API 사용량 전송
                    try:
                        _in_tok  = _api_tokens.get("input", 0)
                        _out_tok = _api_tokens.get("output", 0)
                        telegram_poster.send_publish_notification(
                            title, url, score, word_count, _in_tok, _out_tok,
                            diversity=_diversity
                        )
                    except Exception as e:
                        logging.warning(f"  [Telegram] 텔레그램 알림 발송 실패: {e}")

                    # [API 사용량 누적 로그] 아침 보고용
                    try:
                        _usage_file = META_DIR / "api_usage_log.json"
                        _today = datetime.now().strftime("%Y-%m-%d")
                        _usage_data = {}
                        if _usage_file.exists():
                            _usage_data = json.loads(_usage_file.read_text(encoding="utf-8"))
                        if _today not in _usage_data:
                            _usage_data[_today] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "articles": 0}
                        _usage_data[_today]["input_tokens"]  += _api_tokens.get("input", 0)
                        _usage_data[_today]["output_tokens"] += _api_tokens.get("output", 0)
                        _usage_data[_today]["cost_usd"]      += round((_api_tokens.get("input", 0) * 3.0 + _api_tokens.get("output", 0) * 15.0) / 1_000_000, 6)
                        _usage_data[_today]["articles"]      += 1
                        # 최근 30일만 유지
                        if len(_usage_data) > 30:
                            oldest = sorted(_usage_data.keys())[0]
                            _usage_data.pop(oldest)
                        _usage_file.write_text(json.dumps(_usage_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception as e:
                        logging.warning(f"  [API 사용량 로그] 저장 실패: {e}")
                    
                    # [🚨 CEO 트리거] 1차 실시간 감사 신호 발송
                    try:
                        trigger_path = META_DIR / "new_post_trigger.json"
                        trigger_data = {
                            "title": title,
                            "url": url,
                            "topic": topic,
                            "nutrients": nutrients,
                            "date": datetime.now().strftime("%Y-%m-%d")
                        }
                        trigger_path.write_text(json.dumps(trigger_data, ensure_ascii=False, indent=2), encoding='utf-8')
                        logging.info("  📡 [CEO 트리거] 1차 실시간 감사 신호 발송 완료")
                    except Exception as e:
                        logging.warning(f"  [CEO 트리거] 신호 발송 실패: {e}")

                    try:
                        save_learning(topic, title, "success", issues, score,
                                      archetype_name, topic_type, self.ctx)
                        imprint_success_feedback(topic, score, word_count,
                                                 archetype_name, topic_type)
                        record_retry_effectiveness(topic, critic_retries, published=True)  # [v6.5] API 절감 효과 측정
                    except Exception as _learn_err:
                        logging.warning(f"  [학습저장] 오류 (무시): {_learn_err}")
                    
                    # [v5.9.9.6] (보류) 완성도 9점(90%) 이상 시에만 로컬 위키 자동 동기화
                    # if score >= 0.9:
                    #     try:
                    #         import blog_sync
                    #         blog_sync.run_sync()
                    #         logging.info("  🔄 로컬 위키 동기화 완료 (90%↑)")
                    #     except Exception as e:
                    #         logging.warning(f"  동기화 실패: {e}")

                # 체크포인트는 모니터 루프에서 파일 이동 후 삭제 (재시작 시 URL 정보 보존)
                return True
            else:
                save_learning(topic, title, "failed", issues, score,
                              archetype_name, topic_type, self.ctx)
                report_to_discord("발행오류", f"❌ 발행 실패!\n제목: {title}\n재시도 예정...")
                return False

    # ============================================================
    # 모니터링 루프
    # ============================================================
def monitor():
    logging.info("🤖 NutriStack Grand Orchestrator v5.4")
    logging.info("  ✅ Human Entropy Layer 활성화")
    logging.info("  📐 11가지 아키타입 랜덤 / 섹션 4~8 랜덤 / 단어 1200~4000")
    logging.info("  🔬 YMYL 안전 BANNED_PHRASES v5.4")
    logging.info("  🎯 모델 역할 분리 (Q8/14b/9b/7b/2b)")
    logging.info(f"  📁 모니터링: {RAW_DIR}")

    def _next_scheduled_task():
        """topic_bank.json에서 가장 가까운 pending 작업 반환 (과거 30분 이내 미처리 포함). 없으면 None."""
        topic_bank_path = META_DIR / "topic_bank.json"
        if not topic_bank_path.exists():
            return None
        try:
            bank = json.loads(topic_bank_path.read_text(encoding="utf-8"))
            now = datetime.now()
            cutoff = now - timedelta(minutes=30)  # 30분 이내 과거 미처리도 포함

            candidates = []
            for t in bank:
                if t.get("status") != "pending":
                    continue
                dt_str = f"{t.get('date','')} {t.get('time','00:00')}"
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                    if dt >= cutoff:  # 미래 OR 30분 이내 과거
                        candidates.append((dt, t))
                except ValueError:
                    continue
            if not candidates:
                return None
            candidates.sort(key=lambda x: x[0])
            chosen_dt, chosen_task = candidates[0]

            # ── 즉시 status → "processing" 으로 잠금 (중복 트리거 방지) ──────
            chosen_task["status"] = "processing"
            try:
                topic_bank_path.write_text(
                    json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

            return chosen_dt, chosen_task
        except Exception:
            return None

    def _create_raw_file_from_topic(task: dict) -> Path:
        """topic_bank 항목으로 00_Raw에 .md 파일 생성."""
        topic    = task.get("topic", "Unknown Topic")
        t_type   = task.get("type", "general")
        longtail = task.get("longtail_keywords", [])
        safe     = "".join(c if c.isalnum() or c in "_ -" else "_" for c in topic)[:60]
        out      = RAW_DIR / f"{safe}.md"
        # 예정 시간 기록 — 재시작 후에도 시간 체크 가능하도록
        sched_dt = f"{task.get('date','')} {task.get('time','00:00')}".strip()
        content  = f"# {topic}\ntype: {t_type}\nscheduled_time: {sched_dt}\n"
        if longtail:
            content += "\n## Target Keywords (include naturally in content)\n"
            for kw in longtail:
                content += f"- {kw}\n"
        out.write_text(content, encoding="utf-8")
        return out

    # ── 매일 06:00 트렌드 기반 자동 스케줄러 ──────────────────────────────
    SUPPLEMENT_KEYWORDS = [
        "Taurine", "Berberine", "Glutathione", "Probiotics", "Niacin",
        "NMN", "Vitamin B12", "Citrulline", "Vitamin C", "Magnesium",
        "Vitamin K2", "Vitamin D", "HMB", "Zinc", "Selenium", "SAMe",
        "Iron", "Copper", "Creatine", "Ashwagandha",
        "CoQ10", "NAC", "Collagen", "Omega 3", "Resveratrol",
        "Quercetin", "Lions Mane", "Melatonin", "5-HTP", "L-Theanine",
        "Alpha Lipoic Acid", "Rhodiola", "Spirulina", "Curcumin",
        "Biotin", "Folate", "Vitamin E", "Iodine", "Boron", "Chromium",
    ]

    def _auto_schedule_daily_trends():
        """매일 06:00 한 번 실행: Google Trends 7d/30d/1yr → 미발행 상위 보충제 3개를 topic_bank에 추가."""
        try:
            from pytrends.request import TrendReq
            import random as _rnd

            today_str = datetime.now().strftime("%Y-%m-%d")
            bank_path = META_DIR / "topic_bank.json"
            bank = json.loads(bank_path.read_text(encoding='utf-8'))

            # 오늘 이미 트렌드 스케줄 됐으면 스킵
            already = [t for t in bank if t.get("date") == today_str and t.get("trend_window")]
            if already:
                logging.info(f"  [TrendScheduler] 오늘({today_str}) 이미 {len(already)}개 스케줄됨 — 스킵")
                return

            # 이미 발행된 가이드 목록
            published_path = META_DIR / "published_links.json"
            published_topics = []
            if published_path.exists():
                try:
                    pl = json.loads(published_path.read_text(encoding='utf-8'))
                    published_topics = [(e.get('topic', '') + ' ' + e.get('title', '')).lower() for e in pl]
                except:
                    pass

            def is_published(kw):
                kw_l = kw.lower()
                return any(kw_l in p for p in published_topics)

            # [v8.0] topic_bank.json pending/in_progress 항목도 제외 (중복 스케줄 방지)
            _tb_pending_kws = set()
            try:
                _tb_chk = json.loads((META_DIR / "topic_bank.json").read_text(encoding='utf-8'))
                for _tc in _tb_chk:
                    if _tc.get("status") in ("pending", "in_progress"):
                        _tc_topic = _tc.get("topic", "").lower()
                        for _sk in SUPPLEMENT_KEYWORDS:
                            if _sk.lower() in _tc_topic:
                                _tb_pending_kws.add(_sk)
            except Exception:
                pass

            candidates = [s for s in SUPPLEMENT_KEYWORDS
                          if not is_published(s) and s not in _tb_pending_kws]
            if len(candidates) < 3:
                logging.warning("  [TrendScheduler] 미발행 후보 부족 — 스킵")
                return

            pytrend = TrendReq(hl='en-US', tz=360, timeout=(10, 25))

            WINDOWS = [
                ("7d",  "now 7-d",    [(6,30),(6,47),(7,15),(7,42),(8,10),(8,33)]),
                ("30d", "today 1-m",  [(12,5),(12,33),(13,7),(13,45),(14,12),(14,50)]),
                ("1yr", "today 12-m", [(17,10),(17,40),(18,5),(18,23),(19,0),(19,35)]),
            ]

            def find_top_for_window(timeframe, exclude):
                remaining = [c for c in candidates if c not in exclude]
                best_kw, best_score = None, -1
                for i in range(0, len(remaining), 5):
                    batch = remaining[i:i+5]
                    try:
                        pytrend.build_payload(batch, cat=0, timeframe=timeframe, geo='US')
                        df = pytrend.interest_over_time()
                        if df.empty:
                            continue
                        for kw in batch:
                            if kw in df.columns:
                                score = float(df[kw].mean())
                                if score > best_score:
                                    best_score, best_kw = score, kw
                        time.sleep(2)
                    except Exception as _be:
                        logging.warning(f"  [TrendScheduler] 배치 오류: {_be}")
                        time.sleep(5)
                return best_kw

            used_in_session = []
            added = []
            for idx, (window_key, timeframe, time_pool) in enumerate(WINDOWS):
                top_kw = find_top_for_window(timeframe, used_in_session)
                if not top_kw:
                    logging.warning(f"  [TrendScheduler] {window_key} 후보 없음")
                    continue
                used_in_session.append(top_kw)
                topic_name = f"{top_kw} Complete Guide"
                # [v8.0] 시간/날짜 배정 없이 큐에만 추가 — 실제 시간 배정은 00:01 plan_today()가 담당
                bank.append({
                    "topic": topic_name,
                    "type": "comprehensive_guide",
                    "time": "00:00",
                    "date": "",
                    "status": "pending",
                    "trend_window": window_key,
                    "trend_slot": f"{idx+1}번째",
                })
                added.append(f"{topic_name} @ {t_str} ({window_key})")
                logging.info(f"  [TrendScheduler] 추가: {topic_name} @ {t_str} ({window_key})")

            bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding='utf-8')
            if added:
                try:
                    telegram_poster.send_alert("📊 오늘의 트렌드 스케줄:\n" + "\n".join(f"• {a}" for a in added))
                except:
                    pass
        except Exception as _e:
            logging.warning(f"  [TrendScheduler] 오류: {_e}")

    orch               = GrandOrchestrator()
    last_briefing_day  = -1
    last_analytics_day = -1
    last_trend_day     = -1
    file_fail_counts   = {}   # {filename: fail_count} — ctx 초기화와 무관하게 유지
    FAILED_DIR         = RAW_DIR.parent / "00_Failed"
    FAILED_DIR.mkdir(exist_ok=True)

    # [v9.5] 재시작 시 오늘 날짜 processing 항목 → pending 자동 복원
    # 이유: 재시작마다 _next_scheduled_task()가 pending 항목을 하나씩 processing으로 소진
    # → 반복 재시작 시 모든 슬롯이 processing으로 고착되는 버그 방지
    try:
        _tb_path = META_DIR / "topic_bank.json"
        if _tb_path.exists():
            _tb = json.loads(_tb_path.read_text(encoding="utf-8"))
            _today_str = datetime.now().strftime("%Y-%m-%d")
            _now_hm    = datetime.now().strftime("%H:%M")
            _reset_count = 0
            for _item in _tb:
                # 발행 완료된 항목은 status=completed — processing 상태면 미발행 중단된 것
                if (_item.get("status") == "processing"
                        and _item.get("date", "") == _today_str
                        and _item.get("time", "00:00") > _now_hm):
                    _item["status"] = "pending"
                    _reset_count += 1
            if _reset_count:
                _tb_path.write_text(json.dumps(_tb, ensure_ascii=False, indent=2), encoding="utf-8")
                logging.info(f"  🔄 [v9.5] 재시작 복원: 오늘 processing {_reset_count}개 → pending")
    except Exception as _rst_e:
        logging.warning(f"  [v9.5] 재시작 복원 실패 (무시): {_rst_e}")

    # [v6.5] 재시작 시 60초 대기 — 스케줄러 타이밍 존중
    _startup_files = set(f.name for f in list(RAW_DIR.glob("**/*.txt")) + list(RAW_DIR.glob("**/*.md"))
                         if not f.name.startswith("SKIP_"))
    if _startup_files:
        logging.info(f"  ⏳ 재시작 감지 — 60초 대기 후 처리 (스케줄러 우선)")
        logging.info(f"  📄 대기 파일: {', '.join(_startup_files)}")
        time.sleep(60)
    STARTUP_AT = datetime.now()

    # Initial dashboard sync
    try:
        import dashboard_sync
        dashboard_sync.sync()
    except: pass

    while True:
        now = datetime.now()

        # Dashboard Sync every loop
        try:
            import dashboard_sync
            dashboard_sync.sync()
        except: pass

        if ((now.hour > 7) or (now.hour == 7 and now.minute >= 0)) and now.day != last_analytics_day:
            try:
                from morning_report import send_daily_analytics_report
                send_daily_analytics_report()
            except: pass
            # GA4 실제 성과 → 에이전트 레슨 피드백 (모닝 리포트 직후)
            try:
                fetch_ga4_article_lessons()
            except Exception as _e:
                logging.warning(f"  [GA4 Lesson] 스킵: {_e}")
            last_analytics_day = now.day

        # v8.1: 스케줄링은 daily_scheduler_v5.py 06:00이 전담 — 오케스트레이터 TrendScheduler 비활성
        if now.hour >= 6 and now.day != last_trend_day:
            last_trend_day = now.day  # _auto_schedule_daily_trends() 제거됨

        if ((now.hour > 5) or (now.hour == 5 and now.minute >= 0)) and now.day != last_briefing_day:
            topic_bank = META_DIR / "topic_bank.json"
            if topic_bank.exists():
                try:
                    bank    = json.loads(topic_bank.read_text(encoding='utf-8'))
                    # 오늘 날짜의 pending 항목 모두 가져오기
                    today_str = now.strftime("%Y-%m-%d")
                    pending = [t for t in bank if t.get("status") == "pending" and t.get("date") == today_str]
                    topics  = [{"time": t.get("time","TBD"), "topic": t.get("topic","")} for t in pending]
                    if topics: send_daily_briefing(topics)
                except Exception as e:
                    logging.warning(f"브리핑 오류: {e}")
            last_briefing_day = now.day

        # 00_Raw (실제 발행) + 00_Test (테스트 draft) 둘 다 감지
        _raw_files  = [f for f in list(RAW_DIR.glob("**/*.txt")) + list(RAW_DIR.glob("**/*.md"))
                       if not f.name.startswith("SKIP_")]
        _test_files = [f for f in list(TEST_DIR.glob("**/*.txt")) + list(TEST_DIR.glob("**/*.md"))
                       if not f.name.startswith("SKIP_")]
        if _test_files:
            logging.info(f"  🧪 [TEST] {len(_test_files)}개 테스트 파일 감지")
        files = _raw_files + _test_files
        if files:
            stuck_count = 0
            for f in files:
                _is_test_file = f.parent == TEST_DIR  # 테스트 폴더 여부
                # 파일별 최대 3회 실패 시 격리 (ctx 리셋과 무관하게 누적)
                if file_fail_counts.get(f.name, 0) >= 3:
                    logging.error(f"  🚨 {f.name} 3회 실패 — 00_Failed로 격리")
                    try:
                        shutil.move(str(f), str(FAILED_DIR / f.name))
                    except Exception as e:
                        logging.warning(f"  격리 이동 실패: {e}")
                    file_fail_counts.pop(f.name, None)
                    try:
                        report_to_discord("System", f"🚨 발행 3회 실패 격리: {f.name}")
                    except Exception:
                        pass
                    continue

                logging.info(f"\n📄 파일 감지: {f.name}")

                # ── 예정 시간 체크 — 아직 안 됐으면 스킵 ────────────────────
                try:
                    _raw_lines = f.read_text(encoding='utf-8', errors='ignore').splitlines()
                    _sched_line = next((l for l in _raw_lines if l.startswith("scheduled_time:")), None)
                    if _sched_line:
                        _sched_str = _sched_line.split(":", 1)[1].strip()
                        _sched_dt  = datetime.strptime(_sched_str, "%Y-%m-%d %H:%M")
                        _now_dt    = datetime.now()
                        if _sched_dt > _now_dt:
                            _wait_min = int((_sched_dt - _now_dt).total_seconds() / 60)
                            logging.info(
                                f"  ⏳ [{f.name}] 예정 시간 미도달 "
                                f"({_sched_str}, {_wait_min}분 후) — 대기"
                            )
                            stuck_count += 1
                            continue
                except Exception:
                    pass  # scheduled_time 없는 기존 파일은 즉시 처리

                # [v8.1] 중복발행 방지 — published_links 확인 + Blogger API 실제 존재 검증
                _already_pub = False
                try:
                    _raw_txt   = f.read_text(encoding='utf-8', errors='ignore')
                    _topic_key = _raw_txt.split('\n')[0].lstrip('#').strip().lower()
                    _pl_path   = META_DIR / "published_links.json"
                    if _pl_path.exists() and _topic_key:
                        _pl      = json.loads(_pl_path.read_text(encoding='utf-8'))
                        _today_s = datetime.now().strftime("%Y-%m-%d")
                        for _pe in _pl:
                            _pe_topic = ((_pe.get('topic') or '').split('\n')[0]
                                         .lstrip('#').strip().lower())
                            if _pe.get('date') == _today_s and _pe_topic and (
                                _topic_key in _pe_topic or _pe_topic in _topic_key
                            ):
                                # ── Blogger API로 실제 존재 여부 확인 ──────────
                                _post_id_chk = str(_pe.get('post_id', ''))
                                _live_on_blogger = False
                                if _post_id_chk:
                                    try:
                                        _chk_svc = get_blogger_service()
                                        if _chk_svc:
                                            _chk_svc.posts().get(
                                                blogId=BLOG_ID,
                                                postId=_post_id_chk,
                                                fields="id,status"
                                            ).execute()
                                            _live_on_blogger = True  # 200 OK = 실제 존재
                                    except Exception as _chk_err:
                                        # 404 등 = Blogger에서 삭제됨 → 발행 허용
                                        logging.info(
                                            f"  [중복체크] post_id={_post_id_chk} Blogger에 없음 "
                                            f"(삭제됨) → 발행 허용: {_chk_err}"
                                        )
                                        _live_on_blogger = False
                                else:
                                    # post_id 없으면 published_links만으로 판단
                                    _live_on_blogger = True

                                if _live_on_blogger:
                                    logging.warning(
                                        f"  ⏭️ Blogger에 실제 존재 확인 — 파이프라인 차단: "
                                        f"{_raw_txt.split(chr(10))[0].strip()}"
                                    )
                                    _dest = COMPLETED_DIR / f.name
                                    if _dest.exists(): _dest.unlink()
                                    if f.exists(): shutil.move(str(f), str(_dest))
                                    file_fail_counts.pop(f.name, None)
                                    _already_pub = True
                                else:
                                    logging.info(
                                        f"  ♻️ published_links에는 있으나 Blogger에 없음 "
                                        f"→ 재발행 허용: {_raw_txt.split(chr(10))[0].strip()}"
                                    )
                                break
                except Exception as _ap_err:
                    logging.warning(f"  [중복발행 방지] 체크 오류: {_ap_err}")

                if _already_pub:
                    orch.ctx = {}
                    continue

                _api_tokens["input"] = 0
                _api_tokens["output"] = 0
                ok = False
                try:
                    ok = orch.run(f)
                except Exception as _run_err:
                    import traceback as _tb
                    logging.error(f"  💥 orch.run() 예외 발생: {_run_err}\n{_tb.format_exc()}")
                    # 발행은 됐는데 후처리에서 크래시한 경우 → 체크포인트 URL 확인
                    _cp_url = orch.ctx.get("url", "") or orch.ctx.get("published_url", "")
                    if _cp_url:
                        logging.warning("  ⚠️ 발행 성공 후 크래시 — 파일을 Completed로 이동합니다")
                        ok = True  # 발행은 성공한 것으로 간주
                    else:
                        logging.warning("  ⚠️ 발행 실패 크래시 — Raw 유지")
                try:
                    if ok:
                        # 테스트 파일 → 99_Test_Done, 실제 파일 → 01_Completed
                        dest = (TEST_DONE_DIR if _is_test_file else COMPLETED_DIR) / f.name
                        if dest.exists(): dest.unlink()
                        if f.exists():
                            shutil.move(str(f), str(dest))
                            if _is_test_file:
                                logging.info(f"  🧪 테스트 완료: {f.name} → 99_Test_Done")
                            else:
                                logging.info(f"  ✅ 완료 이동: {f.name}")
                        # 파일 이동 성공 후 체크포인트 삭제 (URL 정보 보존을 위해 여기서 삭제)
                        _cp = CHECKPOINT_DIR / f"{f.stem}.json"
                        if _cp.exists():
                            try:
                                _cp.unlink()
                            except Exception:
                                pass
                        file_fail_counts.pop(f.name, None)
                    else:
                        if not f.exists():
                            # orch.run() 내부에서 이미 이동 처리됨 (중복 감지 등) → 실패 아님
                            file_fail_counts.pop(f.name, None)
                            logging.info(f"  ✅ 내부 처리 완료 (중복 자동이동): {f.name}")
                        else:
                            cnt = file_fail_counts.get(f.name, 0) + 1
                            file_fail_counts[f.name] = cnt
                            logging.warning(f"  ❌ 미션 실패 ({cnt}/3) (Raw에 유지): {f.name}")
                except Exception as e:
                    logging.warning(f"  파일 후처리 실패: {e}")

                orch.ctx = {}

            # 모든 파일이 scheduled_time 미도달로 스킵됐으면 30초 대기 (로그 폭발 방지)
            if stuck_count == len(files):
                time.sleep(30)

        else:
            nxt = _next_scheduled_task()
            if nxt:
                next_dt, next_task = nxt
                secs = (next_dt - datetime.now()).total_seconds()

                if secs <= 0:
                    # [v8.0] RAW 생성 전 published_links 확인 — 이미 발행됐으면 completed 처리 후 스킵
                    _next_topic_str = next_task.get("topic", "")
                    _next_topic_key = _next_topic_str.lower()
                    _already_in_pl  = False
                    _matched_post_id = None
                    try:
                        _pl2 = json.loads((META_DIR / "published_links.json").read_text(encoding='utf-8'))
                        for _pe2 in _pl2:
                            _pe2_t = ((_pe2.get("topic") or "").split("\n")[0]
                                      .lstrip("#").strip().lower())
                            if _pe2_t and (
                                _next_topic_key in _pe2_t or _pe2_t in _next_topic_key
                            ):
                                _matched_post_id = str(_pe2.get("post_id", ""))
                                _already_in_pl = True
                                break
                    except Exception:
                        pass

                    # ── Blogger API 실제 존재 확인 ────────────────────
                    if _already_in_pl and _matched_post_id:
                        try:
                            _sch_svc = get_blogger_service()
                            if _sch_svc:
                                _sch_svc.posts().get(
                                    blogId=BLOG_ID,
                                    postId=_matched_post_id,
                                    fields="id,status"
                                ).execute()
                                # 200 OK → 실제 존재 → 차단 유지
                        except Exception:
                            # 404 → Blogger에 없음 → 재발행 허용
                            logging.info(
                                f"  ♻️ published_links에 있으나 Blogger에 없음 → 재발행 허용: {_next_topic_str}"
                            )
                            _already_in_pl = False

                    if _already_in_pl:
                        logging.warning(
                            f"  ⏭️ 이미 발행됨 — RAW 생성 차단 & topic_bank 완료 처리: {_next_topic_str}"
                        )
                        try:
                            _tb_path2 = META_DIR / "topic_bank.json"
                            _bank2 = json.loads(_tb_path2.read_text(encoding='utf-8'))
                            for _t2 in _bank2:
                                if _t2.get("topic") == _next_topic_str:
                                    _t2["status"] = "completed"
                            _tb_path2.write_text(
                                json.dumps(_bank2, ensure_ascii=False, indent=2), encoding='utf-8'
                            )
                        except Exception as _ce:
                            logging.warning(f"  [스케줄러] completed 처리 실패: {_ce}")
                    else:
                        # 시간이 됐거나 지남 → RAW 파일 즉시 생성
                        logging.info(f"  ⏰ 스케줄 실행: '{_next_topic_str}' — RAW 파일 생성")
                        _create_raw_file_from_topic(next_task)
                        # topic_bank status → in_progress (중복 실행 방지)
                        try:
                            _tb_path = META_DIR / "topic_bank.json"
                            _bank = json.loads(_tb_path.read_text(encoding='utf-8'))
                            for _t in _bank:
                                if (_t.get("topic") == _next_topic_str and
                                        _t.get("date") == next_task.get("date")):
                                    _t["status"] = "in_progress"
                                    break
                            _tb_path.write_text(
                                json.dumps(_bank, ensure_ascii=False, indent=2), encoding='utf-8'
                            )
                        except Exception as _ue:
                            logging.warning(f"  [스케줄러] topic_bank 업데이트 실패: {_ue}")
                else:
                    mins = int(secs // 60)
                    hrs  = mins // 60
                    eta  = f"{hrs}시간 {mins % 60}분" if hrs else f"{mins}분"
                    logging.info(
                        f"  😴 다음 작업: '{next_task.get('topic','')}' "
                        f"({next_task.get('time','')}) — {eta} 후 깨어납니다"
                    )
                    # 60초마다 RAW 파일 체크하며 대기 (스케줄러가 먼저 파일 생성 시 즉시 처리)
                    target = max(secs - 30, 10)
                    elapsed = 0
                    while elapsed < target:
                        chunk = min(60, target - elapsed)
                        time.sleep(chunk)
                        elapsed += chunk
                        if list(RAW_DIR.glob("**/*.txt")) or list(RAW_DIR.glob("**/*.md")):
                            logging.info("  ⚡ RAW 파일 감지 — 즉시 처리합니다")
                            break
            else:
                # 예약 작업 없음 → 60초마다 RAW 파일 체크 (최대 1시간)
                logging.info("  😴 예약된 작업 없음. RAW 파일 생기면 즉시 처리합니다.")
                try:
                    telegram_poster.send_alert("ℹ️ NutriStack: 예약 작업이 없습니다. 스케줄러로 새 주제를 추가해 주세요.")
                except Exception:
                    pass
                for _ in range(60):  # 60 x 60s = 최대 1시간
                    time.sleep(60)
                    if list(RAW_DIR.glob("**/*.txt")) or list(RAW_DIR.glob("**/*.md")):
                        logging.info("  ⚡ RAW 파일 감지 — 즉시 처리합니다")
                        break


if __name__ == "__main__":
    monitor()
