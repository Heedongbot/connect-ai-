"""
NutriStack Lab — Grand Orchestrator v5.4
=========================================
베이스: v4.8 (실제 작동 코드)
v5.0~v5.3: Human Entropy Layer
v5.4: BANNED_PHRASES YMYL 안전 수정
  - "research suggests" → 제거 (과학 언어 유지)
  - "studies indicate"  → 제거 (과학 언어 유지)
  - "clinical evidence shows" → 제거 (과학 언어 유지)
  - 너무 광범위한 단어 치환 제거 (optimize, improve, ensures 등)
"""
import sys, io, os, time, json, re, pickle, random, base64, requests, shutil, logging
from collections import defaultdict
from datetime import datetime
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
        print(f"\n\u26a0\ufe0f [중복 실행 방지] 이미 동일한 프로그램이 실행 중입니다 (포트 {port} 점유 중).")
        print("중복 실행을 방지하기 위해 이 인스턴스를 즉시 종료합니다.\n")
        sys.exit(0)

ensure_single_instance(19999)

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('orchestrator.log',encoding='utf-8'), logging.StreamHandler()])

BASE_DIR       = Path(__file__).parent
RAW_DIR        = BASE_DIR / "00_Raw"
COMPLETED_DIR  = BASE_DIR / "01_Completed"
CHECKPOINT_DIR = BASE_DIR / "02_Checkpoints"
IMAGE_DIR      = BASE_DIR / "05_Images"
PROMPT_DIR     = BASE_DIR / "06_prompts"
LEARN_DIR      = BASE_DIR / "10_Wiki" / "Decisions"
META_DIR       = BASE_DIR / "20_Meta"

for d in [RAW_DIR, COMPLETED_DIR, CHECKPOINT_DIR, IMAGE_DIR, LEARN_DIR, META_DIR]:
    d.mkdir(exist_ok=True, parents=True)

SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/webmasters.readonly'
]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE          = Path("token.pickle")
BLOG_ID             = "2812259517039331714"
OLLAMA_URL          = "http://localhost:11434/api/generate"


HEAVY_MODEL         = "qwen3:14b-q4_K_M"
LIGHT_MODEL         = "qwen2:7b-instruct-q4_0"
MODEL_RESEARCH      = "gemma4:e4b-it-q8_0"
MODEL_WRITER        = "qwen3:8b-q4_K_M"
MODEL_VISUAL_PROMPT = "gemma2:2b"
MODEL_HOOK_CREATIVE = "gemma2:9b"
MODEL_HOOK_TRIM     = "qwen2:7b-instruct-q4_0"
MODEL_TITLE_FAQ     = "qwen3:14b-q4_K_M"
MODEL_LABEL_EXTRACT = "gemma2:2b"
MODEL_LABEL_SEO     = "gemma4:e4b-it-q4_K_M"
MODEL_CRITIC        = "qwen3:14b-q4_K_M"

SD_API_URL  = "http://127.0.0.1:7860"
SD_ENABLED  = True
SDXL_MODEL  = "epicrealismXL_pureFix.safetensors"
SD15_MODEL  = "epicrealismXL_pureFix.safetensors"

LINKS_DB_FILE        = META_DIR / "published_links.json"
PENDING_APPROVAL     = META_DIR / "pending_approval.json"
LESSONS_FILE         = META_DIR / "agent_lessons.json"
GA4_PROPERTY_ID      = "properties/527664358"
BLOG_URL             = "sc-domain:nutristacklab.com"
DISCORD_WEBHOOK_FILE = BASE_DIR / "discord_webhook.json"

# ============================================================
# HUMAN ENTROPY ENGINE
# ============================================================
ARCHETYPES = {
    "science-heavy":    {"weight": 15, "min_words": 2000, "max_words": 4000, "sections": [4,5,6], "faq_prob": 0.7,  "toc_prob": 0.85, "methodology_prob": 1.0,  "kt_prob": 0.95},
    "minimalist":       {"weight": 20, "min_words": 1200, "max_words": 1800, "sections": [3,4],     "faq_prob": 0.3,  "toc_prob": 0.05, "methodology_prob": 1.0,  "kt_prob": 0.5},
    "quick-answer":     {"weight": 15, "min_words": 1000, "max_words": 1400, "sections": [3],       "faq_prob": 0.4,  "toc_prob": 0.05, "methodology_prob": 1.0,  "kt_prob": 0.6},
    "journal-tone":     {"weight": 15, "min_words": 1500, "max_words": 2500, "sections": [4,5],     "faq_prob": 0.5,  "toc_prob": 0.1,  "methodology_prob": 1.0,  "kt_prob": 0.5},
    "nordic-anecdotal": {"weight": 15, "min_words": 1400, "max_words": 2200, "sections": [4,5],     "faq_prob": 0.4,  "toc_prob": 0.1,  "methodology_prob": 1.0,  "kt_prob": 0.6},
    "comparison":       {"weight": 10, "min_words": 1600, "max_words": 2800, "sections": [4,5,6], "faq_prob": 0.6,  "toc_prob": 0.8,  "methodology_prob": 1.0,  "kt_prob": 0.8},
    "deep-protocol":    {"weight": 2,  "min_words": 2500, "max_words": 4000, "sections": [5,6],     "faq_prob": 0.99, "toc_prob": 0.9,  "methodology_prob": 1.0, "kt_prob": 0.99},
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
    "{section} — {topic}.",
    "A closer look at {section} in the context of {topic}.",
    "What the research shows: {section} for {topic}.",
    "Breaking down {section} — {topic}.",
    "The science behind {section} and {topic}.",
    "Clinical perspective: {section} — {topic}.",
    "Understanding {section} when working with {topic}.",
]

def get_next_pattern(patterns, last_file_name, key_id="id"):
    last_file = META_DIR / last_file_name
    last_val = None
    if last_file.exists():
        try: last_val = json.loads(last_file.read_text(encoding='utf-8')).get("last")
        except: pass
    
    if isinstance(patterns[0], dict):
        available = [p for p in patterns if p[key_id] != last_val]
        chosen = random.choice(available)
        new_val = chosen[key_id]
    else:
        available = [p for p in patterns if p != last_val]
        chosen = random.choice(available)
        new_val = chosen
        
    last_file.write_text(json.dumps({"last": new_val}, ensure_ascii=False), encoding='utf-8')
    return chosen

def generate_og_description(topic, title):
    # [v5.9.9.9] 'Common', 'Mistakes' 등 오염 단어 제거 및 영양소 중심 키워드 추출
    black_list = {"common", "mistakes", "tips", "avoid", "timing", "guide", "protocol", "best", "how", "why"}
    topic_clean = re.sub(r'[^\w\s]', ' ', topic).lower()
    keywords = [w for w in topic_clean.split() if len(w) > 3 and w not in black_list]
    
    # 영양소 DB에서 다시 한번 확인
    nutrients = extract_nutrients_from_topic(topic)
    if nutrients:
        kw = ' and '.join(nutrients[:2])
    else:
        kw = ' and '.join(keywords[:2]) if len(keywords) >= 2 else (keywords[0] if keywords else topic[:15])
    
    kw = kw.title() # 첫 글자 대문자
    
    # [v5.9.9.9] 단일 영양소와 조합 영양소 템플릿 분리
    if ' and ' in kw.lower() or ' with ' in kw.lower():
        desc = random.choice(OG_DESC_TEMPLATES_DUAL).format(kw=kw)
    else:
        desc = random.choice(OG_DESC_TEMPLATES).format(kw=kw)
        
    if len(desc) > 155: desc = desc[:152] + "..."
    return desc

def random_caption(section_label, topic):
    template = random.choice(CAPTION_TEMPLATES)
    return template.format(section=section_label, topic=topic[:45])

def inject_meta_description(html, description):
    desc_escaped = description.replace('"', '\\"')
    # [v6.3] JSON-LD, standard meta tags, and a client-side JS meta injector to ensure og:description is never empty even if Blogger strips meta tags in body
    js_injector = (
        f'<script type="text/javascript">\n'
        f'document.addEventListener("DOMContentLoaded", function() {{\n'
        f'  var desc = "{desc_escaped}";\n'
        f'  var tags = [\n'
        f'    {{ name: "description", attr: "name", value: desc }},\n'
        f'    {{ name: "og:description", attr: "property", value: desc }},\n'
        f'    {{ name: "twitter:description", attr: "name", value: desc }}\n'
        f'  ];\n'
        f'  tags.forEach(function(t) {{\n'
        f'    var el = document.querySelector("meta[" + t.attr + "=\'" + t.name + "\']");\n'
        f'    if (el) {{\n'
        f'      el.setAttribute("content", t.value);\n'
        f'    }} else {{\n'
        f'      var meta = document.createElement("meta");\n'
        f'      meta.setAttribute(t.attr, t.name);\n'
        f'      meta.setAttribute("content", t.value);\n'
        f'      document.head.appendChild(meta);\n'
        f'    }}\n'
        f'  }});\n'
        f'}});\n'
        f'</script>\n'
    )
    meta_tags = (
        f'<meta name="description" content="{desc_escaped}">\n'
        f'<meta property="og:description" content="{desc_escaped}">\n'
        f'<meta name="twitter:description" content="{desc_escaped}">\n'
    )
    meta_block = (
        f'<script type="application/ld+json">'
        f'{{"@context":"https://schema.org","@type":"Article",'
        f'"description":"{desc_escaped}"}}'
        f'</script>\n'
    )
    return meta_tags + meta_block + js_injector + html


def pick_archetype():
    names   = list(ARCHETYPES.keys())
    weights = [ARCHETYPES[n]["weight"] for n in names]
    return random.choices(names, weights=weights, k=1)[0]

def get_archetype_config(name, topic_type="synergy"):

    cfg = ARCHETYPES[name]
    cfg = ARCHETYPES[name].copy()
    
    # [v5.4] 주제별 가중치 보정
    boost = 1.0
    if topic_type in ["food-combo", "protocol", "synergy", "antagonism", "deficiency"]:
        boost = 1.3
        
    # [v5.9.9.7] Chaos Factor - 구조 반복 파괴를 위한 랜덤성 주입
    if random.random() < 0.3: cfg["faq_prob"] = 0
    if random.random() < 0.2: cfg["toc_prob"] = 0
    cfg["include_table"] = random.random() > 0.4 # 40% 확률로 표 제외 지시용
    
    return {
        "name":               name,
        "target_words":       random.randint(cfg["min_words"], cfg["max_words"]),
        "section_count":      random.choice(cfg["sections"]),
        "include_faq":        random.random() < min(1.0, cfg["faq_prob"] * boost),
        "include_toc":        random.random() < cfg.get("toc_prob", 0.5),
        "include_methodology":random.random() < min(1.0, cfg["methodology_prob"]),
        "include_kt":         random.random() < min(1.0, cfg["kt_prob"] * boost),
        "include_cliff":      random.random() < 0.4,
        "include_nordic":     random.random() < 0.4,
        "include_table":      cfg.get("include_table", True),
        "image_count":        random.choices([0,1,2,3,4,5], weights=[15,20,25,20,15,5], k=1)[0],
    }

SECTION_POOLS = {
    "synergy": [
        "What Actually Worked Better for Me",
        "The Timing Experiment: My Morning vs Night Results",
        "The Simple Choice I Finally Made",
        "How it Actually Felt During the First Week",
    ],
    "food-combo": [
        "Why I Switched to Taking it After Dinner",
        "The Small Meal Context: What Changed My Results",
        "My Practical Guide to Food Pairing",
        "What I Stopped Eating Simultaneously",
    ],
    "side-effects": [
        "The Reality: What It Actually Felt Like",
        "Common Hiccups I Noticed at First",
        "Why It Might Disrupt Your Evening Routine",
        "Learning to Listen to My Body's Signals",
    ],
    "antagonism": [
        "Why I No Longer Combine These Two",
        "The Real-World Conflict I Encountered",
        "What the Experience Taught Me",
        "Better Alternatives I Found Instead",
    ],
    "recipe": [
        "The Simple Logic Behind My Daily Routine",
        "Exactly How I Prepare It Each Morning",
        "My Observations on Timing and Results",
        "How I Adjust My Dose for Colder Weeks",
    ],
    "mechanism": [
        "What Seems to Happen Inside (In Plain English)",
        "Why Consistent Use Mattered More Than the Dose",
        "Practical Results Over Scientific Theory",
        "How it Changed My Afternoon Energy",
    ],
    "protocol": [
        "My New Daily Routine and Timing",
        "The Common Mistakes I Made at the Start",
        "Tracking My Progress: The One Week Shift",
        "Long-Term Safety: What I'm Watching For",
    ],
    "comparison": [
        "Which One Actually Worked Better for Me?",
        "Morning vs Night: The Comparison",
        "Cost and Practicality: My Choice",
        "Decision Guide: Who Should Try Which",
    ],
    "deficiency": [
        "The Silent Symptoms I Ignored",
        "Who Is Most at Risk in Winter",
        "Food vs Supplements: My Strategy",
        "How Long Until I Felt a Difference",
    ],
    "timing": [
        "Why Timing Changed Everything for Me",
        "My Morning vs Evening Observations",
        "Food Windows and My Daily Schedule",
        "Practical Tips for Better Results",
    ],
}

# ============================================================
# 아키타입 설정 (Style & Depth)
# ============================================================
# ARCHETYPE_CONFIGS deprecated in favor of ARCHETYPES

def get_sections_for_type(topic_type, count):
    pool = SECTION_POOLS.get(topic_type, SECTION_POOLS["synergy"])
    return random.sample(pool, min(count, len(pool)))

def detect_topic_type(topic):
    t = topic.lower()
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
INTERNAL_LINKS = [
    {"title":"The Master Magnesium Protocol — How and When to Take It","url":"https://www.nutristacklab.com/2026/03/the-master-protocol-how-and-when-to.html"},
    {"title":"Is Your Magnesium Leaking Before It Reaches Your Cells?","url":"https://www.nutristacklab.com/2026/03/is-your-magnesium-leaking-before-it.html"},
    {"title":"Magnesium's Hidden Partners — The Ultimate Synergy Stack","url":"https://www.nutristacklab.com/2026/03/magnesiums-hidden-partners-ultimate.html"},
    {"title":"The Blood-Brain Barrier — Why Your Standard Choline Fails","url":"https://www.nutristacklab.com/2026/04/the-blood-brain-barrier-why-your.html"},
    {"title":"Alpha-GPC vs CDP Choline — The Ultimate Brain Fuel","url":"https://www.nutristacklab.com/2026/04/alpha-gpc-vs-cdp-choline-ultimate-brain.html"},
    {"title":"The Nordic Creatine Protocol — Dosage for Brain Optimization","url":"https://www.nutristacklab.com/2026/04/the-nordic-creatine-protocol-dosage-for.html"},
    {"title":"L-Theanine and Caffeine — The Alpha Wave Protocol","url":"https://www.nutristacklab.com/2026/04/l-theanine-and-caffeine-alpha-wave.html"},
    {"title":"The Brain Fog Mushroom — What Lion's Mane Actually Does","url":"https://www.nutristacklab.com/2026/03/the-brain-fog-mushroom-what-lions-mane.html"},
    {"title":"The Memory Herb — What Bacopa Monnieri Actually Does","url":"https://www.nutristacklab.com/2026/03/the-memory-herb-what-bacopa-monnieri.html"},
    {"title":"The Dark Season Paradox — Why Your Vitamin D3 Is Failing","url":"https://www.nutristacklab.com/2026/03/the-dark-season-paradox-why-your.html"},
    {"title":"The Omega-3 Deficiency Signal — Why Your Brain Is Inflamed","url":"https://www.nutristacklab.com/2026/03/the-omega-3-deficiency-signal-why-your.html"},
    {"title":"Mørketid — The Complete Science of Nordic Darkness","url":"https://www.nutristacklab.com/2026/04/morkketid-science-nordic-darkness-body.html"},
    {"title":"The Free Testosterone Switch — Why You Need Boron","url":"https://www.nutristacklab.com/2026/04/the-free-testosterone-switch-why-you.html"},
    {"title":"The Nordic L-Theanine Dosage Protocol — Timing and Stacks","url":"https://www.nutristacklab.com/2026/04/the-nordic-l-theanine-dosage-protocol.html"},
]

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

def save_link_to_db(title, url, topic, nutrients):
    db = load_links_db()
    if any(l.get("url","") == url for l in db): return
    db.append({"title": title, "url": url, "topic": topic,
                "nutrients": nutrients, "date": datetime.now().strftime("%Y-%m-%d"),
                "category": detect_category(topic)})
    LINKS_DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
    logging.info(f"  🔗 링크 DB 저장: {title[:40]}")

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

def find_related_links(topic, count=5):
    db = load_links_db()
    all_links = list(INTERNAL_LINKS)
    for entry in db:
        if not any(l["url"] == entry.get("url","") for l in all_links):
            all_links.append(entry)
    topic_nutrients = extract_nutrients_from_topic(topic)
    topic_lower = topic.lower()
    scored = []
    for link in all_links:
        score = 0
        link_title    = link.get("title","").lower()
        link_nutrients= [n.lower() for n in link.get("nutrients", [])]
        link_topic    = link.get("topic","").lower()
        for nut in topic_nutrients:
            if nut in link_title or nut in link_topic: score += 3
            if nut in link_nutrients: score += 2
        for nut in topic_nutrients:
            for rel in NUTRIENT_RELATIONS.get(nut, []):
                if rel in link_title or rel in link_topic: score += 2
        if link.get("category","") == detect_category(topic): score += 1
        for word in topic_lower.split():
            if len(word) > 4 and word in link_title: score += 1
        if score > 0: scored.append((score, link))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [link for _, link in scored[:count]]
    if len(selected) < count:
        remaining = [l for l in all_links if l not in selected]
        bad_markers = [
            "here are", "proposed title", "options:", "the is protocol", 
            "the and protocol", "the with protocol", "why and vitamin",
            "best:", "simpler way to think about ginger", "practical look at why and",
            "when people prefer when", "nutrient vs and", "the is ",
            "blood: timing", "when people prefer", " and and ", "ps and omega",
            "alpha and gpc", "dup and ", "maximize and ", "vitamin and d",
            "never combine why"
        ]
        cleaned_data = []
        for entry in remaining:
            title = entry.get("title", "").lower()
            if len(title) < 15: continue
            if any(m in title for m in bad_markers): continue
            if title.startswith(("write ", "task ", "here ", "best:", "the is ")): continue
            cleaned_data.append(entry)
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
        "Guide": "Notes",
        "Common": "",
        "Mistakes": "Errors",
    }
    new_title = title
    for k, v in replacements.items():
        new_title = re.sub(rf'(?i)\b{k}\b', v, new_title)
    
    # 중복 공백 제거 및 정리
    new_title = re.sub(r'\s+', ' ', new_title).strip()
    return new_title

def is_duplicate(topic):
    topic_lower = topic.lower().strip()
    topic_words = set(re.sub(r'[^\w\s]', ' ', topic_lower).split())
    db   = load_links_db()
    stop = {"the","and","or","a","an","of","for","in","with","vs","is","your","how","why",
            "nordic","protocol","stack","guide","science","benefits","complete","ultimate"}
    t_words = topic_words - stop
    for entry in db:
        existing_title = entry.get("title","").lower()
        existing_topic = entry.get("topic","").lower()
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

def load_agent_with_lessons(filename):
    base_prompt   = load_agent(filename) # load_agent에서 이미 reinforcement 주입됨
    agent_key     = filename.replace(".md", "")
    lessons       = load_lessons()
    agent_lessons = lessons.get(agent_key, [])
    if not agent_lessons: return base_prompt
    recent = agent_lessons[-15:]
    lessons_block = "\n\n## ⚠️ DYNAMIC FEEDBACK FROM PAST REJECTIONS (FIX THESE):\n"
    for i, l in enumerate(recent, 1):
        lessons_block += f"{i}. [{l['date']}] {l['lesson']}\n"
    logging.info(f"  🧠 [{agent_key}] 다이나믹 피드백 {len(recent)}개 주입")
    return base_prompt + lessons_block

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
    lessons   = load_lessons()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated   = []
    for agent_key, lesson_text in lessons_parsed.items():
        if not lesson_text or str(lesson_text).lower() in ["null","none",""]: continue
        file_key = AGENT_FILE_MAP.get(agent_key, agent_key)
        if file_key not in lessons: lessons[file_key] = []
        
        # 점수 요약표와 지시사항을 합쳐 영양가 높은 피드백으로 완성
        full_lesson = f"{score_summary} {str(lesson_text).strip()}"
        lessons[file_key].append({
            "date": timestamp, "topic": topic[:40],
            "attempt": attempt_num, "lesson": full_lesson[:300]
        })
        lessons[file_key] = lessons[file_key][-20:]
        updated.append(agent_key)
    save_lessons(lessons)
    logging.info(f"  ✅ 레슨 각인 완료: {updated}")

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

def ask_ai(prompt, system_prompt, model=HEAVY_MODEL, max_retries=2, timeout=600):
    clean_instruction = (
        f"{prompt}\n\nSTRICT: Output ONLY the requested content. "
        "No instructions. No markdown. No preamble. Start immediately."
    )
    for attempt in range(max_retries):
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": model, "prompt": clean_instruction, "system": system_prompt,
                "stream": False, "options": {"temperature": 0.4, "top_p": 0.9, "repeat_penalty": 1.2, "repeat_last_n": 64}
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
        # ★ PMID 날조 방지 패치: 7-10자리 숫자 + 현재 상한선(4000만) 이하만 허용
        pmids  = [str(p["pmid"]) for p in papers if str(p["pmid"]).isdigit() and 7 <= len(str(p["pmid"])) <= 8 and int(p["pmid"]) < 40000000]
        if pmids:
            logging.info(f"  🔬 PubMed 실제 논문 {len(pmids)}개 검증 완료")
            return pmids
    except Exception as e:
        logging.warning(f"  PubMed 실패 → 폴백: {e}")
    
    t = topic.lower()
    for key, pool_pmids in PMID_DB.items():
        if key in t:
            # 검증된 숫자만 추출
            valid_pool = [str(p) for p in pool_pmids if str(p).isdigit() and int(p) < 40000000]
            if not valid_pool: continue
            return random.sample(valid_pool, min(count, len(valid_pool)))
    
    # 기본 폴백에서도 숫자 검증
    default_pool = [str(p) for p in PMID_DB.get("default", []) if str(p).isdigit() and int(p) < 40000000]
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

IMAGE_STYLE_DB = {
    "magnesium":   "magnesium crystal mineral structure glowing teal, neural pathways",
    "vitamin d":   "golden vitamin D sunlight rays through nordic winter clouds, molecular",
    "vitamin d3":  "vitamin D3 cholecalciferol molecule golden rays Arctic winter sky",
    "omega":       "omega-3 fish oil DHA EPA molecular structure deep ocean Nordic",
    "omega-3":     "omega-3 fatty acid molecule fish oil capsules Arctic fjord backdrop",
    "zinc":        "zinc mineral crystal lattice immune cells glowing blue dark background",
    "l-theanine":  "l-theanine green tea molecule alpha brain waves calm Nordic forest",
    "theanine":    "theanine molecule zen calm neural alpha waves Nordic dark winter",
    "creatine":    "creatine ATP energy molecule glowing brain cell mitochondria dark",
    "lion":        "lion's mane mushroom glowing neural network NGF protein forest dark",
    "bacopa":      "bacopa monnieri plant neural synapses memory pathway purple glow",
    "collagen":    "collagen triple helix protein structure skin joint tissue Nordic",
    "vitamin c":   "vitamin C ascorbic acid molecule immune cells citrus crystalline",
    "quercetin":   "quercetin flavonoid molecule immune defense cell golden Nordic",
    "coq10":       "coq10 ubiquinol mitochondria energy production cell glowing orange",
    "nmn":         "NMN NAD+ molecule longevity DNA repair aging reversal blue glow",
    "berberine":   "berberine alkaloid molecule metabolic pathway AMPK activation gold",
    "probiotics":  "probiotic bacteria gut microbiome neural axis dark scientific",
    "glutathione": "glutathione antioxidant molecule detox pathway emerald green glow",
    "ashwagandha": "ashwagandha withanolide molecule stress cortisol calm Nordic night",
    "rhodiola":    "rhodiola rosea adaptogen molecule energy fatigue resistance Arctic",
    "glucosamine": "glucosamine cartilage joint molecule structural repair Nordic",
    "boron":       "boron mineral testosterone hormone SHBG molecule Nordic dark",
    "pqq":         "PQQ mitochondria biogenesis CREB pathway cellular energy orange",
    "default":     "supplement molecule neural network glowing dark Nordic winter",
}

SECTION_VISUAL_THEMES = {
    "hero": "Cinematic wide-angle shot, {style}, masterpiece, 8k, professional photography, Nordic aurora background",
    "s1":   "Macro extreme close-up, {style}, molecule floating in liquid, depth of field, sharp focus, laboratory vibe",
    "s2":   "Neural pathway visualization, {style}, glowing synaptic sparks, intricate connections, dark background, 3D render",
    "s3":   "Top-down flat-lay composition, {style}, supplement bottles and natural ingredients on a clean stone surface, soft natural light",
    "s4":   "Abstract scientific data visualization, {style}, holographic charts, medical interface, futuristic medical technology",
    "s5":   "Daily routine lifestyle shot, {style}, a person holding a supplement glass in a minimalist kitchen, morning soft sunlight",
    "s6":   "Comparison split-screen view, {style}, two different molecular structures side by side, technical blueprint style",
    "s7":   "Biological clock timeline, {style}, rotating gears mixed with molecular structures, 4D time-lapse concept",
    "s8":   "Advanced lab equipment view, {style}, high-tech centrifuge and microscopic slides, sterile environment",
}

VISUAL_DIRECTIONS = [
    "Moody dramatic shadows, cinematic teal and orange color grading",
    "Minimalist clean aesthetic, soft white lighting, high-key photography",
    "Cyberpunk neon accents, glowing fluorescent molecules, dark aesthetic",
    "Natural organic vibe, warm sunset lighting, earthy tones",
    "Hyper-realistic scientific 3D render, Octane render, unreal engine 5 style",
    "Professional editorial studio lighting, sharp edges, premium brand look",
]

def get_image_prompt(topic, img_key):
    topic_lower = topic.lower()
    style = IMAGE_STYLE_DB.get("default","supplement molecule")
    for keyword, img_style in IMAGE_STYLE_DB.items():
        if keyword != "default" and keyword in topic_lower:
            style = img_style; break
    
    theme = SECTION_VISUAL_THEMES.get(img_key, SECTION_VISUAL_THEMES["hero"])
    direction = random.choice(VISUAL_DIRECTIONS)
    
    # [v5.8] 주제 키워드 결합 및 시각적 다양성 주입
    final_prompt = f"{theme.format(style=style)}, {direction}, highly detailed, 8k"
    return final_prompt[:250]


def _sd_generate(prompt, is_hero=True):
    if not SD_ENABLED: return None
    try:
        model  = SD15_MODEL
        steps  = 25 if is_hero else 20
        width, height = (768, 1152) if is_hero else (896, 512)
        payload = {
            "prompt": prompt,
            "negative_prompt": "watermark, text, logo, blurry, low quality",
            "steps": steps, "width": width, "height": height, "cfg_scale": 7.0,
            "sampler_name": "DPM++ 2M Karras",
            "override_settings": {"sd_model_checkpoint": model},
        }
        r = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=300)
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
        if not local_ok: _create_fallback_png(img_path)
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
    key_words_full = [w for w in words if re.sub(r'[^\w]', '', w.lower()) not in stop_words and len(re.sub(r'[^\w]', '', w.lower())) > 2]
    topic_label = " ".join(key_words_full[:2]).title() if key_words_full else "Supplement"
    
    bad_labels = ["Stopped", "Stop", "Taking", "Take", "Started", "Using", "Use", "Found", "Actually", "Truth", "Comparing", "Combining", "Trying", "Testing", "Avoid"]
    for bl in bad_labels:
        if bl in topic_label: topic_label = topic_label.replace(bl, "").strip()
    if "Zinc" in topic.title(): topic_label = "Zinc"
    if not topic_label: topic_label = "Supplement"

    key_words = []
    for w in words:
        clean_w = re.sub(r'[^\w]', '', w.lower())
        if clean_w not in stop_words and len(clean_w) > 2:
            key_words.append(w.strip(',.:;'))
            
    # [v6.2] Fallback if key_words is empty after filtering
    if not key_words:
        key_words = [w.strip(',.:;') for w in words if len(re.sub(r'[^\w]', '', w)) > 2]
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
        "side-effects": f"{topic_label} Side Effects: What the Data Shows",
        "antagonism":   f"Why You Shouldn't Combine {' and '.join(key_words[:2])}",
        "food-combo":   f"Best Foods to Combine With {topic_label}",
        "deficiency":   f"Common Signs of {topic_label} Deficiency",
        "timing":       f"When to Take {topic_label}: A {power_word} Timing Guide",
        "recipe":       f"The {topic_label} Protocol: A {power_word} Recipe",
        "comparison":   f"{key_words[0]} vs {key_words[1] if len(key_words) >= 2 else 'Alternative'}: Which Is Better?",
    } if key_words else {}

    if topic_type in type_styles:       base_title = type_styles[topic_type]
    elif archetype_name in arch_styles: base_title = arch_styles[archetype_name]
    else:                               base_title = None

    prompt = (
        f"Task: Write ONE SEO-optimized blog post title that sounds like a real person's question on Reddit.\n"
        f"Topic: {topic}\nArticle style: {archetype_name}\n"
        f"Key nutrients: {', '.join(key_words)}\n"
        + (f"Base title idea: {base_title}\n" if base_title else "")
        + f"CRITICAL: Start with a problem, symptom, or a direct question (Why, How, Should, Does).\n"
        f"Requirements: max 58 chars. No quotes. No numbering. No 'Title:' prefix.\n"
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
            first = f"{A} vs {B}: My Choice After Testing"
        elif topic_type in ["food-combo", "recipe"]:
            first = f"Why I Pair {A} With Specific Foods"
        elif topic_type == "side-effects":
            first = f"What {A} Actually Feels Like: Side Effects"
        elif topic_type == "antagonism":
            first = f"Why I Never Combine {A} and {B}"
        elif topic_type == "timing":
            first = f"When I Take {A}: Morning vs Evening Results"
        else:
            first = f"How I Use {A} Effectively: My Findings"
        
        logging.warning(f"  ⚠️ 제목 오염 감지 → 주제({topic_type}) 맞춤형 자가 수정 ({retry_count}회)")

    first = first.replace('"','').replace("'","").strip()
    # 문장 첫 글자 대문자 보장
    first = first[0].upper() + first[1:] if first else ""
    
    # [v6.3] 최종 제목 정제: 'Common' 등 불필요한 단어 제거 (최종 필터)
    clean_title = re.sub(r'(?i)\b(common|mistakes|tips|avoid|guide|protocol|mechanism|mechanisms|synergy|combination|combinations)\b\s*', '', first).strip()
    # 'and and' 또는 문장 시작의 'and ' 등 정제
    clean_title = re.sub(r'\b(and|with)\s+(and|with)\b', 'and', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    if clean_title.lower().startswith("and "): clean_title = clean_title[4:]
    if clean_title.lower().endswith(" and"): clean_title = clean_title[:-4]
    
    # [v5.9.9.9] 'Combine and Zinc' -> 'Taking Zinc' 같은 자연스러운 변환 (옵션)
    clean_title = re.sub(r'(?i)\bcombine\s+and\b', 'Taking', clean_title)
    
    if len(clean_title) > 60: clean_title = clean_title[:57]+"..."
    
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
    topic_words_sec = [w.strip(':,.') for w in topic.split() if w.lower() not in stop_sec and len(w) > 2]
    topic_label = " and ".join(topic_words_sec[:2]) if len(topic_words_sec) >= 2 else (topic_words_sec[0] if topic_words_sec else topic)
    topic_label = topic_label.strip(': ')
    
    # [v5.9.9.9] topic_label에서도 Common/Mistakes 제거 및 'And ' 접두사 방지
    topic_label = re.sub(r'(?i)\b(common|mistakes|tips|avoid|guide|protocol)\b', '', topic_label).strip()
    topic_label = re.sub(r'(?i)^(and|with)\s+', '', topic_label).strip()
    topic_label = topic_label.title()

    disc = ('<p><em>Disclosure: This post may contain affiliate links. '
            'Purchases made through these links support NutriStack Lab '
            'at no additional cost to you.</em></p>')

    hero_url = images.get("hero","[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]")
    # [v5.9.8] 이미지 캡션 및 alt 랜덤화 (Footprint 제거)
    hero_alts = [
        f"A bottle of {topic_label} on a wooden kitchen counter",
        f"{topic_label} supplements next to a bowl of oatmeal",
        f"Testing {topic_label} during a busy work week",
        f"A simple setup for my morning {topic_label} routine"
    ]
    hero_caps = [
        f"My {topic_label} testing routine.",
        f"A closer look at {topic_label} timing.",
        f"Personal observations on {topic_label}.",
        f"Adjusting my {topic_label} routine for the season."
    ]
    hero = build_img_html(hero_url, random.choice(hero_alts), random.choice(hero_caps))

    takeaways = ""
    if include_kt:
        kt_raw = ask_ai(
            f"Write exactly 3 Key Takeaway bullet points for a blog post about: {topic}\n"
            f"Output: 3 plain text lines only. No HTML. No bullets.",
            "Write concise factual bullet points. Output 3 plain lines only.", LIGHT_MODEL
        ).strip()
        kt_lines = [re.sub(r'^\d+[\.\)]\s*', '', l.lstrip('-* ').strip()) for l in kt_raw.splitlines() if l.strip()][:3]
        if len(kt_lines) < 3:
            kt_lines = [
                f"{topic_label} supports targeted health outcomes through well-researched mechanisms.",
                f"Clinical research shows measurable benefits when dosage and timing are consistent.",
                f"Pairing with complementary nutrients may enhance the overall effect.",
            ]
        # clean_banned 적용 (기존 누락 버그 수정)
        kt_html = "".join([f"<li>{clean_banned(l)}</li>" for l in kt_lines])
        takeaways = (
            '<div style="background:#f0f7ff; border-left:4px solid #2a6496; padding:16px; margin:20px 0;">'
            f'<strong>Key Takeaways</strong><ul>{kt_html}</ul></div>'
        )

    clean_hook = clean_html(hook)
    if arch in ["journal-tone","nordic-anecdotal"]:
        hook_block = f'<hr>\n<p><em>{clean_hook}</em></p>\n<hr>'
    elif arch in ["quick-answer","minimalist"]:
        hook_block = f'<p>{clean_hook}</p>'
    else:
        hook_block = f'<hr>\n<p>{clean_hook}</p>\n<hr>'

    toc_html  = ""
    sec_keys  = list(sections.keys())
    if include_toc and len(sec_keys) >= 3:
        # [v5.7] Blogger 404 방지를 위해 상대 경로 앵커만 사용 + 리스트 스타일 개선
        toc_items = "".join([f'<li><a href="#sec{i}">{s}</a></li>' for i, s in enumerate(sec_keys)])
        if include_faq: toc_items += '<li><a href="#faq">Frequently Asked Questions</a></li>'
        toc_html = (
            '<div style="background:#f9f9f9; border:1px solid #ddd; padding:15px; '
            'margin:20px 0; border-radius:8px;">'
            '<strong style="font-size:1.1em;">Contents</strong>'
            f'<ul style="margin-top:10px; list-style-type:none; padding-left:5px; line-height:1.8;">{toc_items}</ul></div>'
        )


    body = ""
    for i, (sec_name, content) in enumerate(sections.items()):
        clean_content = clean_html(content)
        sec_img = ""
        img_key = f"s{i+1}"
        if i < img_count - 1 and images.get(img_key):
            # [v5.6] 랜덤 캡션 적용
            caption = random_caption(sec_name, topic)
            sec_img = build_img_html(images[img_key], f"{topic.lower()} {sec_name.lower()}", caption)

        pmid_block = ""
        if i < len(pmids):
            pid = pmids[i]
            # [v5.9.9.4] PMID 문구 로테이션 적용 (META_DIR 사용)
            idx_file = META_DIR / "last_pmid_variation.json"
            last_idx = 0
            if idx_file.exists():
                try: last_idx = int(idx_file.read_text())
                except: last_idx = 0
            
            pmid_variations = [
                f"Clinical data via PMID {pid} confirms measurable progress in this area.",
                f"According to research found in PMID {pid}, these specific markers showed clear improvement.",
                f"Data published under PMID {pid} validates the physiological response discussed here.",
                f"As noted in PMID {pid}, researchers observed significant shifts in target bioavailability.",
                f"Further evidence from PMID {pid} supports the timing and dosage protocol outlined.",
                f"Investigation under PMID {pid} revealed a consistent correlation with these outcomes.",
                f"Clinical findings from PMID {pid} provide the empirical basis for this section.",
            ]
            new_idx = (last_idx + 1) % len(pmid_variations)
            idx_file.write_text(str(new_idx))
            
            pmid_text = pmid_variations[new_idx]
            pmid_block = (f'<blockquote><p>Research published via '
                         f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pid}/" '
                         f'rel="noopener noreferrer">PMID {pid}</a>: {pmid_text}</p></blockquote>')

        body += f'\n<h2 id="sec{i}">{sec_name}</h2>\n{sec_img}\n{pmid_block}\n{clean_content}\n'

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
        for q, a in faq_pairs[:4]:
            cq = re.sub(r'<[^>]+>','',q).strip()
            ca = re.sub(r'<[^>]+>','',a).strip()
            faq_html += f'<h3>{cq}</h3>\n<p>{ca}</p>\n'
        schema = build_faq_schema(faq_pairs[:4])

    methodology = ""
    if include_meth:
        methodology = (
            '<h2>About This Article</h2>'
            '<p>This article was written by Erik Lindström based on a personal review of '
            'peer-reviewed literature via PubMed. All scientific claims are linked directly '
            'to their primary sources. This is intended for educational purposes only '
            'and does not constitute medical advice.</p>'
        )

    disclaimer = (
        '<p style="font-size:0.85em;color:#666666;"><em>This content is for informational purposes only '
        'and does not constitute medical advice. Please read our full '
        '<a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html" '
        'rel="noopener noreferrer">Medical Disclaimer</a> '
        'before acting on any information provided.</em></p>'
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
    return final, schema, clean_title

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
            "ultimate guide", "complete guide", "the truth about supplement",
        ]
        if any(p in h1 for p in GENERIC_H1):
            issues.append(f"Generic H1 template: '{h1_m.group(1)[:60]}'")

    # 3. Meta description 누락 또는 비어있음
    meta_m = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    )
    if not meta_m or len(meta_m.group(1).strip()) < 20:
        issues.append("Meta description 누락 또는 너무 짧음")

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
        "PMID_Valid":      not any(int(p) > 40000000 for p in re.findall(r'PMID\s*(\d+)', html, re.IGNORECASE)),
        "AI_Footprint":    not any(p in html.lower() for p in ["interestingly", "notably", "surprisingly", "moreover", "furthermore", "magic hour", "consistency is king", "pairing routine"]),
        "Alt_Clean":       not any(bad in html for bad in ["And Zinc", "Stopped And", "Taking And", "Stop And", "Take And", "Trying And", "Comparing And", "Using And"]) and all(not alt.strip().startswith("And ") for alt in re.findall(r'alt="([^"]*)"', html)),
        "Repetition_Free": not has_repetitive_paragraphs(html),
        "NoPlaceholder":   not _qa_leakage_issues(html),
    }
    score  = sum(checks.values()) / len(checks)
    issues = [k for k,v in checks.items() if not v]
    return score, issues, word_count

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
def publish_to_blogger(title, content, labels=[], meta_desc="", is_draft=False, post_id=None):

    svc = get_blogger_service()
    if not svc: return False
    clean_title  = title.strip()[:200]
    clean_labels = []
    for l in labels[:10]:
        ls = str(l).strip()
        if len(ls) > 50 or '\n' in ls or '**' in ls: continue
        lc = re.sub(r'[^\w\-]','',ls)[:50]
        if lc: clean_labels.append(lc)
    if not clean_labels:
        clean_labels = ["Supplements","NordicHealth","NutriStackLab"]
    
    body = {
        "title": clean_title,
        "content": content,
        "labels": clean_labels,
        "searchDescription": meta_desc[:150] if meta_desc else ""
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
            res = svc.posts().insert(blogId=BLOG_ID,body=body,isDraft=is_draft).execute()
            return res.get('url', res.get('id','published'))
        except Exception as e:
            logging.error(f"  Blogger 오류: {e}")
            try:
                body.pop("labels",None)
                res = svc.posts().insert(blogId=BLOG_ID,body=body,isDraft=is_draft).execute()
                logging.info("  ✅ 라벨 없이 재발행 성공")
                return res.get('url', res.get('id','published'))
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
        is_draft_mode = ("test_" in file_path.name.lower())
        
        while True: # [🚨 v5.5] 재귀 대신 루프 사용


            topic = ""
            task_type = "NEW" # 기본값

            # 파일명에서 태스크 타입 추출
            if "[REWRITE]" in file_path.name: task_type = "REWRITE"
            elif "[RESTORE_IMAGE]" in file_path.name: task_type = "RESTORE_IMAGE"

            # [v5.7] Ghost Purge: 모든 접두사와 BOM, 불필요한 문자열 제거
            topic = raw_text
            # BOM 및 특수 문자 제거
            topic = topic.encode('ascii', 'ignore').decode('ascii') 
            # 접두사 청소 루프
            prefixes = [r'^TOPIC:\s*', r'^Title:\s*', r'^\[.*?\]', r'^P[12]\s*[-_]*\s*']
            for p in prefixes:
                topic = re.sub(p, '', topic, flags=re.IGNORECASE | re.MULTILINE).strip()
            
            topic = topic.replace("_"," ").replace("-"," ").strip()
            # 최종 확인: 혹시라도 남아있을 'TOPIC:' 단어 제거
            topic = re.sub(r'(?i)topic:\s*', '', topic).strip()

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
                topic_type     = detect_topic_type(topic)
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
                sys_p = load_agent_with_lessons("02_Researcher_Synergy.md")
                try:
                    from learning_engine import get_prompt_context
                    learn_ctx = get_prompt_context()
                except: learn_ctx = ""
                
                self.ctx["research"] = ask_ai(
                    f"Topic: {topic}\nArticle Type: {archetype_name} / {topic_type}\n"
                    f"Research this health topic for a Nordic supplement blog.\n"
                    f"Focus: mechanisms, clinical evidence, {topic_type} context, practical application.\n"
                    f"Include: specific enzyme names, receptor interactions, clinical dosages.\n{learn_ctx}",
                    sys_p, MODEL_RESEARCH
                )
                save()
            report_to_discord("Researcher", "📚 리서치 완료 → 섹션 작성 시작")

            # Step 2: 섹션 작성 [qwen2.5:14b]
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            writer_agent  = load_agent_with_lessons("03_Writer_Gardener.md")
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

                    logging.info(f"  ✍️ {sec} [{archetype_name}] ({current_words} words)")
                    report_to_discord("Writer", f"✍️ {sec} ({current_words} words)")

                    # [v5.9.9.7] 표 제외 지시 반영 (Chaos Factor)
                    table_instruction = "" if archetype_cfg.get("include_table", True) else "\nSTRICT: DO NOT include any HTML tables in this section."
                    
                    sec_sys_dynamic = (
                        f"{writer_agent}\n\n{feedback_instruction}\n\n"
                        f"ARTICLE ARCHETYPE: {archetype_name}\n"
                        f"TOPIC TYPE: {topic_type}\n"
                        f"TARGET: {current_words} words per section\n"
                        f"HUMAN TONE: {tone_instr}\n"
                        f"CRITICAL: ONE SECTION ONLY. HTML <p> tags ONLY. NO markdown. NO headers.{table_instruction}\n"
                        f"Research context: {self.ctx.get('research','')[:1500]}"
                    )
                    self.ctx["sections"][sec] = ask_ai(
                        f"Write the '{sec}' section for: {topic}\n"
                        f"Article type: {archetype_name} / Topic type: {topic_type}\n"
                        f"Target: {current_words} words. HTML <p> tags only.\n{density_instr}",
                        sec_sys_dynamic, MODEL_WRITER
                    )
                    save()

            # Step 3: 이미지 [SDXL hero / SD1.5 sections]
            if "images" not in self.ctx: self.ctx["images"] = {}                    
            img_count = archetype_cfg["image_count"]

            if "hero" not in self.ctx["images"]:
                img_desc = get_image_prompt(topic, "hero")
                fn = f"{file_path.stem}_hero.png"
                self.ctx["images"]["hero"] = get_image_url(img_desc, fn, IMAGE_DIR / fn)
                save()

            for i in range(1, min(img_count, len(sections_list)+1)):
                key = f"s{i}"
                if key not in self.ctx["images"]:
                    img_desc = get_image_prompt(topic, key)
                    fn = f"{file_path.stem}_{key}.png"
                    self.ctx["images"][key] = get_image_url(img_desc, fn, IMAGE_DIR / fn)
                    save()

            # Step 4: Hook (v5.6 10종 로테이션)
            if "hook" not in self.ctx:
                pattern = get_next_pattern(HOOK_PATTERNS, "last_hook_pattern.json")
                logging.info(f"  🎣 Hook [v5.6 패턴: {pattern['id']}]...")
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
                    body_ctx = " ".join(list(self.ctx["sections"].values())[:3])[:1200]
                    self.ctx["faq"] = ask_ai(
                        f"Topic: {topic}\n\nAUTHOR'S EXPERIENCE (MUST FOLLOW): {body_ctx}\n\n"
                        f"Create 3 FAQ pairs in HTML. IMPORTANT: Your answers MUST be 100% consistent with the author's experience above. "
                        f"If the author felt nausea with food, the FAQ must NOT suggest taking it with food.\n"
                        f"Format: <h3>Question?</h3>\n<p>Answer (50-80 words)</p>\nHTML only.",
                        "FAQ specialist. Consistent with provided text.", MODEL_TITLE_FAQ
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

            # JSON-LD 메타 정보 주입 (v5.6)
            html = inject_meta_description(html, meta_desc)


            # Step 9: 품질 검사 + Critic [gemma4:e4b-it-q8_0]
            try:
                import dashboard_sync
                dashboard_sync.sync()
            except: pass

            score, issues, word_count = quality_check(html + schema, title, archetype_name)
            pmid_count = len(re.findall(r'PMID\s*\d+', html, re.IGNORECASE))
            logging.info(f"  📊 품질: {score:.1%} | 단어: {word_count} | PMID: {pmid_count}")

            logging.info("  🎯 Critic 검증 [gemma4 Q8]...")
            critic_sys    = load_agent_with_lessons("05_Critic_Editor_In_Chief.md")
            html          = clean_ai_output(html)
            critic_result = ask_ai(
                f"Topic: {topic}\nArchetype: {archetype_name}\nTopic Type: {topic_type}\n"
                f"Title: {title}\nWord Count: {word_count}\nPMID Count: {pmid_count}\n"
                f"Issues: {issues}\nFull Article Content:\n{html[:35000]}\n\n"
                f"IMPORTANT: This is a '{archetype_name}' article.\n"
                f"- minimalist/quick-answer/short-practical: "
                f"{ARCHETYPES.get(archetype_name,{}).get('min_words',1200)}+ words. TOC/FAQ optional.\n"
                f"- science-heavy/deep-protocol: 2000+ words, PMID citations required.\n"
                f"Evaluate based on archetype standards.\n"
                f"Output: APPROVED or REJECTED\nReason (Korean, specific):",
                critic_sys, MODEL_CRITIC, max_retries=1
            )

            critic_retries = self.ctx.get("critic_retries", 0)
            history        = self.ctx.get("rejection_history", [])
            
            # [v5.9.9.9] 자동 검사 이슈가 있으면 AI 판단과 무관하게 REJECT 강제 (91% 승인 방지)
            if issues and "REJECTED" not in critic_result.upper():
                logging.warning(f"  🚨 자동 검사 이슈 발견 ({len(issues)}건) -> AI 승인 무효화 및 반려 처리")
                critic_result = f"REJECTED\n자동 검증 이슈: {', '.join(issues)}"
            
            is_rejected    = "REJECTED" in critic_result.upper()

            if is_rejected:
                critic_retries += 1
                self.ctx["critic_retries"] = critic_retries
                is_loop = False
                if len(history) >= 3:
                    # Normalize history strings to avoid false negatives due to whitespace/ case differences
                    normalized = [h[:50].lower().strip() for h in history[-3:]]
                    if (len(set(normalized)) == 1 or critic_retries >= 3):
                        is_loop = True
                        if critic_retries >= 3:
                            actual_word_count = len(re.sub(r'<[^>]+>',' ',html).split())
                            if actual_word_count < 1000:
                                logging.error(f"  🚨 단어 수 미달 — 발행 차단 ({actual_word_count} words)")
                                report_to_discord("System", f"🚨 발행 차단 (단어수 미달): {topic[:40]} ({actual_word_count}단어)")
                                return False  # 강제승인 대신 차단
                            
                            # [v6.2] 자동 검증 이슈가 있으면 루프가 감지되더라도 강제 승인 차단 (애드센스 승인 보장)
                            if issues:
                                logging.error(f"  🚨 루프 감지되었으나 자동 검증 이슈({len(issues)}건) 존재하여 강제 승인 불가 — 발행 차단")
                                report_to_discord("System", f"🚨 발행 차단 (루프 감지되었으나 검증 실패): {topic[:40]}\n이슈: {', '.join(issues)}")
                                return False
                            
                            # 1000단어 이상만 강제승인
                            logging.error(f"  🚨 루프 감지! 강제 승인 ({critic_retries}회, {actual_word_count} words)")
                            report_to_discord("System", f"🚨 루프 감지 강제 승인: {topic[:40]}")
                            is_rejected = False
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
                    report_to_discord("Critic", f"🔴 반려 ({critic_retries}/3)\n{critic_result[:200]}")
                    imprint_critic_feedback(topic, critic_result, critic_retries)
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

                    if backtrack in ["RESEARCHER","RESEARCH"]:
                        keys_to_clear = ["research","sections","hook","title","faq"]
                    elif backtrack in ["WRITER","CONTENT"]:
                        keys_to_clear = ["sections","faq"]
                    elif backtrack in ["PERSONA","HOOK"]:
                        keys_to_clear = ["hook"]
                    elif backtrack in ["SEO","TITLE"]:
                        keys_to_clear = ["title"]
                    else:
                        keys_to_clear = ["sections","hook","title","faq"]

                    # v5.4: 반려 시 즉시 학습
                    save_learning(topic, title, "rejected",
                                  [critic_result[:200]], score, archetype_name, topic_type, self.ctx)

                    for k in keys_to_clear: self.ctx.pop(k, None)
                    save()
                    logging.info(f"  🔄 [Backtrack] {backtrack} 단계로 돌아가 재시도합니다.")
                    continue # [🚨 v5.5] 재귀 대신 루프 처음으로 이동


            if not is_rejected:
                logging.info("  ✅ Critic 승인!")
                report_to_discord("Critic", f"✅ 승인: {title[:40]}")
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
            url       = publish_to_blogger(title, html, labels, meta_desc=meta_desc, is_draft=is_draft_mode, post_id=self.ctx.get("post_id"))



            if url:
                logging.info(f"  ✅ 발행 완료: {url}")
                report_to_discord("Chronos-X",
                    f"🏆 발행!\n📝 {title}\n📐 {archetype_name}/{topic_type}\n"
                    f"📊 {word_count:,}단어 / {score:.0%}\n🔗 {url}")
                
                # [🚨 v5.5] 테스트 모드인 경우 기록 생략 (데이터 오염 방지)
                if is_draft_mode:
                    logging.info("  🛡️ 테스트 모드: DB 기록 및 학습을 생략합니다.")
                else:
                    nutrients = extract_nutrients_from_topic(topic)
                    # post_to_pinterest_auto(title, url, hero_img)  # API 연결 후 활성화
                    # post_to_twitter_auto(title, url, hero_img, tweet_text)
                    save_link_to_db(title, url, topic, nutrients)
                    
                    # [Telegram 연동] 블로거 발행 후 텔레그램 채널로 알림 전송
                    try:
                        telegram_poster.send_telegram_notification(title, url)
                    except Exception as e:
                        logging.warning(f"  [Telegram] 텔레그램 알림 발송 실패: {e}")
                    
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

                    save_learning(topic, title, "success", issues, score,
                                  archetype_name, topic_type, self.ctx)
                    
                    # [v5.9.9.6] (보류) 완성도 9점(90%) 이상 시에만 로컬 위키 자동 동기화
                    # if score >= 0.9:
                    #     try:
                    #         import blog_sync
                    #         blog_sync.run_sync()
                    #         logging.info("  🔄 로컬 위키 동기화 완료 (90%↑)")
                    #     except Exception as e:
                    #         logging.warning(f"  동기화 실패: {e}")

                # Ensure checkpoint file is removed even if later steps raise unexpected errors
                try:
                    if cp.exists():
                        cp.unlink()
                except Exception as e:
                    logging.warning(f"  체크포인트 삭제 실패: {e}")
                return True
            else:
                save_learning(topic, title, "failed", issues, score,
                              archetype_name, topic_type, self.ctx)
                report_to_discord("Chronos-X", f"❌ 발행 실패: {title}")
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

    orch               = GrandOrchestrator()
    last_briefing_day  = -1
    last_analytics_day = -1

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

        if ((now.hour > 6) or (now.hour == 6 and now.minute >= 50)) and now.day != last_analytics_day:
            try:
                from morning_report import send_daily_analytics_report
                send_daily_analytics_report()
            except: pass
            last_analytics_day = now.day

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

        files = list(RAW_DIR.glob("*.txt"))
        if files:
            for f in files:
                logging.info(f"\n📄 파일 감지: {f.name}")
                ok = orch.run(f)
                try:
                    if ok: # 성공 시에만 이동
                        dest = COMPLETED_DIR / f.name
                        if dest.exists(): dest.unlink()
                        if f.exists():
                            shutil.move(str(f), str(dest))
                            logging.info(f"  ✅ 완료 이동: {f.name}")
                    else:
                        logging.warning(f"  ❌ 미션 실패 (Raw에 유지): {f.name}")
                except Exception as e:
                    logging.warning(f"  파일 후처리 실패: {e}")

                orch.ctx = {}

        else:
            logging.info(f"  💤 대기 중... ({RAW_DIR}에 .txt 파일을 넣으세요)")
        time.sleep(10)


if __name__ == "__main__":
    monitor()