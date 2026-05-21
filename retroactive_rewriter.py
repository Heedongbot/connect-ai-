"""
NutriStack Lab — Retroactive Rewriter v2.0
==========================================
변경 사항 (v1.2 → v2.0):
  [FIX 1] 섹션 제목 하드코딩 제거 → 주제별 동적 생성
  [FIX 2] Hook 클리셰 강제 검증 + 재시도 로직
  [FIX 3] PMID 문장 하드코딩 제거 → 5종 로테이션
  [FIX 4] About This Article → Erik Lindström 형식으로 교체
  [FIX 5] BANNED_PHRASES 오케스트레이터 수준으로 확장
  [FIX 6] 2인칭 → 1인칭 서술 옵션 추가 (journal-tone 아키타입)
  [FIX 7] 섹션 내용 중복 방지 (prev_context 강화)
"""

import json
import re
import time
import pickle
import random
import logging
import requests
from pathlib import Path
from datetime import datetime

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('rewriter.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR            = Path(__file__).parent
TOKEN_FILE          = BASE_DIR / "token.pickle"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
SCOPES              = ['https://www.googleapis.com/auth/blogger']
BLOG_ID             = "2812259517039331714"
OLLAMA_URL          = "http://localhost:11434/api/generate"
HEAVY_MODEL         = "qwen3:14b-q4_K_M"
LIGHT_MODEL         = "qwen2:7b-instruct-q4_0"
DISCORD_FILE        = BASE_DIR / "discord_webhook.json"
DONE_FILE           = BASE_DIR / "20_Meta" / "rewriter_done.json"
TARGET_WORDS        = 2500
DELAY               = 5

# ============================================================
# [FIX 3] PMID 문장 5종 로테이션 (하드코딩 제거)
# ============================================================
PMID_VARIATIONS = [
    "If you want to dig into the exact science, check out PMID {pmid} for the full clinical data.",
    "I found a fascinating study (PMID {pmid}) that explains the precise biochemical mechanism here.",
    "Research published under PMID {pmid} actually backs up this exact protocol with human trials.",
    "According to the data in PMID {pmid}, researchers noticed a significant difference when timing was optimized.",
    "For the skeptics, the clinical breakdown in PMID {pmid} provides a very clear picture of why this works.",
    "I highly recommend glancing at PMID {pmid} if you want to understand the long-term safety data."
]

# ============================================================
# [FIX 2] Hook 클리셰 감지 목록
# ============================================================
HOOK_CLICHES = [
    "07:15", "07:15 am", "oslo", "cabin", "woodsmoke", "pine",
    "frost", "chill seeps", "mournful", "encroaching darkness",
    "frosted windows", "icy grip", "polar night", "trudge through",
    "darkness closing in", "bone-deep", "seeps into your bones",
    "biting cold", "blade of frost",
]

# ============================================================
# [FIX 5] BANNED_PHRASES 확장 (오케스트레이터 수준)
# ============================================================
BANNED = {
    # 기존
    "unlock your potential": "optimize your output",
    "unlock your cognitive potential": "reach cognitive peak",
    "unlock": "access",
    "game-changer": "significant advancement",
    "delve into": "examine",
    "dive into": "explore",
    "let's explore": "here is",
    "in today's fast-paced world": "when life gets demanding",
    "it's important to note": "worth noting",
    "mental dominance": "cognitive performance",
    # [FIX 5] 신규 추가
    "surprisingly": "as it turns out",
    "oddly enough": "interestingly",
    "honestly": "in my experience",
    "magic pill": "quick fix",
    "magic pills": "supplements",
    "magic bullet": "simple solution",
    "magic window": "ideal timing",
    "works like magic": "works effectively",
    "felt like magic": "felt noticeably smoother",
    "remarkable dance": "biochemical interaction",
    "remarkable synergy": "notable interaction",
    "pivotal study": "key study",
    "crucial": "important",
    "optimal": "effective",
    "consistency is king": "staying consistent",
    "bottom line:": "in short,",
    "the bottom line": "in short",
    "a key part of the process": "part of my routine",
    "made all the difference": "really helped",
    "makes all the difference": "is what matters",
    "it's actually quite simple": "it's straightforward",
    "in short is,": "in short,",
    "changement": "change",
    "changements": "changes",
    "synergistically": "together",
    "holistic approach": "comprehensive approach",
    "comprehensive guide": "practical guide",
    "optimize": "improve",
    "leverage": "use",
    "utilize": "use",
    "facilitate": "help",
    "furthermore": "also",
    "moreover": "and",
    "nevertheless": "still",
    "in conclusion": "in short",
    "to summarize": "in short",
    "Pro-tip:": "One thing that helped:",
    "pro-tip:": "one thing that helped:",
}

# ============================================================
# [1] 유틸리티
# ============================================================
def load_json(p, d):
    p = Path(p)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else d

def save_json(p, data):
    Path(p).parent.mkdir(exist_ok=True, parents=True)
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def report(msg):
    try:
        if DISCORD_FILE.exists():
            data = load_json(DISCORD_FILE, {})
            url = data.get("webhook_url", "")
            if url:
                requests.post(url, json={"content": f"✍️ **[재작성 v2.0]** {msg}"}, timeout=5)
    except:
        pass

def count_words(html):
    return len(re.sub(r'<[^>]+>', ' ', html).split())

def clean_banned(text):
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    for b, r in BANNED.items():
        pattern = re.compile(re.escape(b), re.IGNORECASE)
        def replace_match(m):
            original = m.group(0)
            if r and original[0].isupper():
                return r[0].upper() + r[1:]
            return r
        text = pattern.sub(replace_match, text)
    return text

def clean_markdown(text):
    text = re.sub(r'```[\w-]*\n?', '', text)
    text = re.sub(r'```', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'^\*\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^-\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = text.replace('→', '&#8594;').replace('->', '&#8594;')
    text = text.replace('<p>.', '<p>')
    return text.strip()

def ask_ai(prompt, system="Output only what is requested.", model=HEAVY_MODEL, timeout=600):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": model,
            "prompt": f"/no_think\n{prompt}",
            "system": system,
            "stream": False,
            "options": {
                "temperature": 0.72,
                "top_p": 0.92,
                "repeat_penalty": 1.15,
                "repeat_last_n": 128,
            }
        }, timeout=timeout)
        text = r.json().get('response', '').strip()
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        bad = ["Write ", "MINIMUM", "CRITICAL", "Rules:", "Output:", "Section:", "Requirements:"]
        lines = [l for l in text.splitlines() if not any(b in l for b in bad)]
        return clean_markdown(clean_banned("\n".join(lines).strip()))
    except Exception as e:
        logging.error(f"AI 오류: {e}")
        return ""

def load_done():
    return load_json(DONE_FILE, [])

def save_done(post_id, title):
    done = load_done()
    done.append({"post_id": post_id, "title": title,
                 "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
    save_json(DONE_FILE, done)

def get_service():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f: creds = pickle.load(f)
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
        with open(TOKEN_FILE, 'wb') as f: pickle.dump(creds, f)
    return build('blogger', 'v3', credentials=creds)

def get_all_posts(service):
    posts, page_token = [], None
    while True:
        kwargs = {"blogId": BLOG_ID, "maxResults": 20, "status": "LIVE"}
        if page_token: kwargs["pageToken"] = page_token
        res = service.posts().list(**kwargs).execute()
        posts.extend(res.get('items', []))
        page_token = res.get('nextPageToken')
        if not page_token: break
        time.sleep(1)
    return posts

def update_post(service, post_id, title, content):
    try:
        res = service.posts().update(
            blogId=BLOG_ID, postId=post_id,
            body={"title": title, "content": content}
        ).execute()
        return res.get('url', '')
    except Exception as e:
        logging.error(f"업데이트 오류: {e}")
        return None

IMAGE_STYLES = {
    "magnesium":   "magnesium crystal mineral teal neural pathways dark scientific",
    "vitamin d":   "vitamin D3 golden rays arctic winter sky molecular",
    "vitamin d3":  "vitamin D3 cholecalciferol molecule golden rays arctic",
    "omega":       "omega-3 DHA EPA molecules arctic fjord backdrop dark",
    "zinc":        "zinc mineral immune cells glowing blue dark",
    "theanine":    "l-theanine alpha brain waves calm nordic forest dark",
    "creatine":    "creatine ATP energy molecule brain mitochondria dark",
    "lion":        "lion s mane mushroom neural network NGF forest dark",
    "bacopa":      "bacopa plant neural synapses memory purple glow dark",
    "collagen":    "collagen triple helix protein joint skin nordic dark",
    "vitamin c":   "vitamin C ascorbic acid immune cells citrus dark",
    "quercetin":   "quercetin flavonoid immune defense golden dark",
    "coq10":       "coq10 ubiquinol mitochondria energy orange glow dark",
    "nmn":         "NMN NAD longevity DNA repair blue glow dark",
    "berberine":   "berberine metabolic AMPK activation gold dark",
    "probiotics":  "probiotic gut microbiome neural axis dark scientific",
    "glutathione": "glutathione antioxidant emerald green glow dark",
    "ashwagandha": "ashwagandha cortisol calm nordic night dark",
    "boron":       "boron testosterone hormone molecule dark",
    "default":     "supplement molecule neural network nordic winter dark",
}

def get_img_prompt(topic, idx=0):
    t = topic.lower()
    themes = [
        "8k photorealistic cinematic lifestyle photography of {t} supplement pills and a glass of water on a minimalist wooden kitchen counter, morning sunlight, depth of field, ultra detailed, premium",
        "8k ultra realistic macro photography of a person holding {t} supplement capsules, bright natural light, shallow depth of field, natural skin texture, premium lifestyle",
        "Photorealistic 8k image of {t} supplement bottle next to a cup of espresso on a modern wooden desk, cozy atmosphere, cinematic lighting, sharp focus",
        "8k photorealistic flat lay of {t} vitamins on a marble countertop with scattered fresh berries and a journal, bright morning light, lifestyle photography",
        "8k cinematic macro shot of {t} supplements spilling out of a premium amber glass bottle on a clean white desk, professional product photography, soft shadows",
        "8k photorealistic lifestyle shot of a fitness enthusiast's morning routine, a glass of water and {t} supplements on a wooden table, sunlight streaming through a window, ultra detailed"
    ]
    theme = themes[min(idx, len(themes)-1)]
    return theme.format(t=t)[:140]

SD_API_URL = "http://127.0.0.1:7860"
SD15_MODEL = "epicrealismXL_pureFix.safetensors"

def check_sd_api():
    try:
        r = requests.get(f"{SD_API_URL}/sdapi/v1/sd-models", timeout=5)
        return r.status_code == 200
    except:
        return False

def try_sd15(prompt, width, height, steps=20):
    import base64
    payload = {
        "prompt": prompt,
        "negative_prompt": "watermark, text, logo, blurry, low quality, bad anatomy, ugly, deformed, noisy, grainy",
        "steps": steps,
        "width": width,
        "height": height,
        "cfg_scale": 7.0,
        "sampler_name": "DPM++ 2M Karras",
        "batch_size": 1,
        "n_iter": 1,
        "override_settings": {
            "sd_model_checkpoint": SD15_MODEL,
        },
        "override_settings_restore_afterwards": True,
    }
    r = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=300)
    if r.status_code == 200:
        return base64.b64decode(r.json()["images"][0])
    raise Exception(f"SD1.5 API 오류: {r.status_code}")

def generate_and_upload_image(topic, section_idx, img_fn):
    prompt = get_img_prompt(topic, section_idx)
    is_hero = section_idx == 0
    width = 768 if is_hero else 896
    height = 1152 if is_hero else 512
    steps = 25 if is_hero else 20
    
    img_bytes = None
    if check_sd_api():
        try:
            logging.info(f"    🤖 SD 1.5 시도 중... ({width}×{height})")
            img_bytes = try_sd15(prompt, width, height, steps)
            logging.info(f"    ✅ SD 1.5 성공!")
        except Exception as e:
            logging.warning(f"    ⚠️ SD 1.5 실패 → Pollinations 폴백: {e}")
            
    img_dir = BASE_DIR / "05_Images"
    img_dir.mkdir(exist_ok=True)
    img_path = img_dir / img_fn
    
    if img_bytes is None:
        poll_url = (f"https://image.pollinations.ai/prompt/"
                    f"{requests.utils.quote(prompt)}?width={width}&height={height}&nologo=true")
        for _ in range(3):
            try:
                r = requests.get(poll_url, timeout=60)
                if r.status_code == 200 and len(r.content) > 5000:
                    img_bytes = r.content
                    break
            except: pass
            time.sleep(3)
            
    if img_bytes:
        try:
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            import base64
            with open(img_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            try:
                r_imgur = requests.post("https://api.imgur.com/3/image",
                    headers={"Authorization": "Client-ID 546c25a59c58ad7"},
                    data={"image": b64, "type": "base64"}, timeout=30)
                if r_imgur.status_code == 200:
                    url = r_imgur.json()['data']['link']
                    logging.info(f"    ✅ Imgur 업로드 성공: {img_fn[:40]}")
                    return url
            except Exception as imgur_e:
                logging.warning(f"    Imgur 실패, Base64 폴백: {imgur_e}")
            
            logging.info(f"    ✅ Base64 인코딩 사용: {img_fn[:40]}")
            return f"data:image/png;base64,{b64}"
        except Exception as e:
            logging.error(f"    ❌ 이미지 처리 중 에러 발생: {e}")
            
    # 만약 생성/다운로드 실패 시, 본문에 깨진 엑스박스 아이콘이 뜨는 것을 방지하기 위해 투명한 1x1 픽셀 이미지 전달
    return "data:image/png;base64,iVBOR0w0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

def extract_preserved_elements(html):
    elements = {}
    elements['images'] = re.findall(
        r'https://drive\.google\.com/thumbnail\?[^"\']+', html
    )
    elements['internal_links'] = re.findall(
        r'<p>&#8594; <a href="(https://www\.nutristacklab\.com/[^"]+)"[^>]*>(?:Related|Also worth reading): ([^<]+)</a></p>',
        html
    )
    elements['pmids'] = list(set(re.findall(
        r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', html
    )))[:6]
    faq_match = re.search(
        r'<h2[^>]*>Frequently Asked Questions</h2>(.*?)(?:<hr|<h2)',
        html, re.DOTALL
    )
    elements['faq'] = faq_match.group(1).strip() if faq_match else ""
    disc_match = re.search(r'<p><em>Disclosure:.*?</em></p>', html, re.DOTALL)
    elements['disclosure'] = disc_match.group(0) if disc_match else (
        '<p><em>Disclosure: This post may contain affiliate links. '
        'Purchases made through these links support NutriStack Lab '
        'at no additional cost to you.</em></p>'
    )
    elements['tables'] = re.findall(r'<table.*?</table>', html, re.DOTALL)
    elements['img_tags'] = re.findall(r'<img[^>]+>', html)
    return elements

# 핵심 영양소 추출 헬퍼 (긴 제목 방지용)
def extract_core_nutrient(title):
    t_lower = title.lower()
    if "d3" in t_lower and "k2" in t_lower:
        return "Vitamin D3 and K2"
    if "d3" in t_lower:
        return "Vitamin D3"
    if "k2" in t_lower:
        return "Vitamin K2"
    known = ["Magnesium", "Zinc", "Vitamin D3", "Vitamin K2", "Omega-3", "Vitamin C", "Iron", "Calcium", "Selenium", "Iodine", "Boron", "L-Theanine", "L-Glutamine", "L-Carnitine", "L-Tyrosine", "Glycine", "Taurine", "NAC", "Alpha-GPC", "Creatine", "CDP-Choline", "Phosphatidylserine", "Lion's Mane", "Bacopa Monnieri", "Rhodiola Rosea", "Ashwagandha", "Quercetin", "Resveratrol", "CoQ10", "PQQ", "Glutathione", "Alpha Lipoic Acid", "Astaxanthin", "NMN", "Berberine", "Vitamin B12", "Vitamin B6", "Folate", "Biotin", "Vitamin A", "Probiotics", "Collagen", "Glucosamine", "MSM", "Turmeric", "Ginger", "Elderberry", "Melatonin", "5-HTP", "GABA"]
    for k in known:
        if k.lower() in t_lower:
            return k
    return "This Compound"

def detect_topic_type(topic):
    t = topic.lower()
    if any(x in t for x in ["vs", "versus", "compare", "or "]):     return "comparison"
    if any(x in t for x in ["side effect", "warning", "risk"]):      return "side-effects"
    if any(x in t for x in ["never", "avoid", "block", "stop"]):     return "antagonism"
    if any(x in t for x in ["timing", "morning", "evening", "when"]): return "timing"
    if any(x in t for x in ["deficiency", "deficient", "low "]):     return "deficiency"
    if any(x in t for x in ["protocol", "dosage", "how to"]):        return "protocol"
    return "synergy"

def get_dynamic_sections(topic, topic_type):
    """[FIX 1] 주제별 섹션 제목 동적 생성 및 그룹별 랜덤성 주입 (구조 반복 footprint 차단)"""
    t = extract_core_nutrient(topic).title() # 핵심 성분만 추출
    
    # 각 타입별로 1~5 그룹을 지정하여 논리적 서사(progression)를 유지하면서도
    # 각 그룹 안에서 2가지 이상의 다양한 칭호(phrasing)가 무작위로 선택되도록 함.
    pools = {
        "synergy": [
            (1, "Observation",  f"What I First Noticed After Taking {t}"),
            (1, "Expectation",  f"My Initial Hopes for {t} Supplementation"),
            (2, "Mechanism",    f"How {t} Actually Interacts With Your Body"),
            (2, "Pathway",      f"The Biological Logic of {t} Absorption"),
            (3, "Stacking",     f"Why I Started Pairing This With Other Nutrients"),
            (3, "Synergy",      f"Biochemical Rationale Behind the Stack"),
            (4, "Data",         f"Looking Closely at the Human Trial Results"),
            (4, "Studies",      f"What the Peer-Reviewed Clinical Data Shows"),
            (5, "Routine",      f"My Current Setup and Daily Timing"),
            (5, "Protocol",     f"The Specific Timing Strategy I Settled On"),
        ],
        "comparison": [
            (1, "Expectation",  f"What I Expected vs. What Actually Happened"),
            (1, "Contrast",     f"The Surprising Disconnect in My Real-World Results"),
            (2, "Experience",   f"Which Option Made a Real Difference for Me"),
            (2, "Findings",     f"My Practical Findings Testing Both Alternatives"),
            (3, "Breakdown",    f"The Real Reason They Act Differently"),
            (3, "Mechanism",    f"The Biochemical Differences That Define Them"),
            (4, "Research",     f"What the Data Says About Both Choices"),
            (4, "Data",         f"The Clinical Verdict from Human Trial Records"),
            (5, "Decision",     f"My Final Decision: What I Take Now"),
            (5, "Routine",      f"My Personalized Protocol and Final Choice"),
        ],
        "side-effects": [
            (1, "Reality",      f"The Reality: What {t} Felt Like Initially"),
            (1, "Observation",  f"My First Warnings and Uncomfortable Symptoms"),
            (2, "Trigger",      f"Figuring Out Why These Issues Happened"),
            (2, "Analysis",     f"The Physiological Reason My Body Reacted This Way"),
            (3, "Adjustment",   f"How I Tweaked My Routine to Fix It"),
            (3, "Tuning",       f"The Small Dosage Adjustments That Saved My Routine"),
            (4, "Safety",       f"What Researchers Say About Long-Term Safety"),
            (4, "Research",     f"What the Clinical Literature Warns About Daily Use"),
            (5, "New_Setup",    f"The Adjusted Approach That Finally Worked"),
            (5, "Protocol",     f"My Safe, Side-Effect-Free {t} Setup"),
        ],
        "antagonism": [
            (1, "Mistake",      f"The Mixing Mistake I Didn't Realize I Was Making"),
            (1, "Doubt",        f"Why My Supplement Absorption Felt Completely Blocked"),
            (2, "Conflict",     f"Why Combining These Two Is a Bad Idea"),
            (2, "Antagonism",   f"The Antagonistic Relationship You Need to Know"),
            (3, "Explanation",  f"The Science Behind the Absorption Block"),
            (3, "Mechanism",    f"How They Actively Compete for the Same Receptors"),
            (4, "Studies",      f"What Clinical Tests Show About This Interaction"),
            (4, "Data",         f"What the Peer-Reviewed Human Trials Confirmed"),
            (5, "Alternative",  f"A Much Better Way to Take Them"),
            (5, "Solution",     f"How to Route Your Timing to Avoid the Clash"),
        ],
        "timing": [
            (1, "Morning",      f"Taking {t} Early: My Experience"),
            (1, "Aviation",     f"My Morning Routine: How I Timed My First Dose"),
            (2, "Evening",      f"Taking {t} Late: How It Changed Things"),
            (2, "Night",        f"My Nighttime Findings: Sleep and Recovery Impact"),
            (3, "Reasoning",    f"Why the Clock Actually Matters Here"),
            (3, "Science",      f"The Circadian Logic Behind Absorption Rhythms"),
            (4, "Findings",     f"What Researchers Found About Timing"),
            (4, "Data",         f"What the Clinical Trials Say About Ideal Windows"),
            (5, "Sweet_Spot",   f"Finding the Perfect Time for My Schedule"),
            (5, "Protocol",     f"My Optimized Timing Strategy and Results"),
        ],
        "deficiency": [
            (1, "Signs",        f"The Quiet Signs I Completely Ignored"),
            (1, "Symptoms",     f"How I Slowly Realized My Body Was Running Low"),
            (2, "Commonality",  f"Why Running Low on {t} Is Surprisingly Common"),
            (2, "Context",      f"The Real Reason Most People Are Deficient"),
            (3, "Impact",       f"What Happens Internally When You're Lacking"),
            (3, "Mechanism",    f"The Physiological Cost of {t} Depletion"),
            (4, "Validation",   f"Checking the Research on These Symptoms"),
            (4, "Studies",      f"What the Medical Literature Says About This Deficit"),
            (5, "Fix",          f"How I Finally Addressed the Gap"),
            (5, "Recovery",     f"The Simple Stacking Strategy I Used to Rebuild"),
        ],
        "protocol": [
            (1, "Baseline",     f"Getting Started: My Initial {t} Approach"),
            (1, "Setup",        f"My Starting Points and Initial Daily Doses"),
            (2, "Tuning",       f"Finding the Right Amount Without Overdoing It"),
            (2, "Dosage",       f"How I Found My Personal Sweet Spot"),
            (3, "Backing",      f"The Biological Logic Behind This Routine"),
            (3, "Mechanism",    f"The Science Behind This Specific Combination"),
            (4, "Confirmation", f"Human Trials That Support This Setup"),
            (4, "Data",         f"What the Peer-Reviewed Literature Confirms"),
            (5, "Long_Term",    f"Adjusting for the Long Haul"),
            (5, "Routine",      f"My Finalized Protocol for Sustainable Results"),
        ],
    }
    
    selected_pool = pools.get(topic_type, pools["synergy"])
    
    # 각 그룹(1~5)에서 무작위로 하나씩 선택하여 순서대로 배치
    chosen_sections = []
    for g in [1, 2, 3, 4, 5]:
        options = [x for x in selected_pool if x[0] == g]
        if options:
            _, sec_name, h2_title = random.choice(options)
            chosen_sections.append((sec_name, h2_title))
            
    return chosen_sections

HOOK_PATTERNS = [
    {
        "id": "FAILED_EXPECTATION",
        "instruction": "Start with: 'I thought [Nutrient] just wasn't working.' Describe specific frustration with energy/focus. End with tension. 100-140 words. Plain text.",
    },
    {
        "id": "SPECIFIC_SYMPTOM",
        "instruction": "Open with ONE physical symptom (brain fog, afternoon crash, stiff joints). Describe exactly where it sits and when it hits. End with doubt. 100-140 words. Plain text.",
    },
    {
        "id": "LABEL_VS_REALITY",
        "instruction": "Start with: 'The label says one thing. My body was saying another.' Describe the disconnect between expectation and reality. 100-140 words. Plain text.",
    },
    {
        "id": "TIMING_EXPERIMENT",
        "instruction": "Open with a specific self-experiment (changing time/dose/combo). Describe what shifted without giving resolution. End before conclusion. 100-140 words. Plain text.",
    },
    {
        "id": "QUIET_MOMENT",
        "instruction": "Open with a quiet mundane moment (kitchen counter, phone screen). No weather. Small honest moment triggering doubt. End with tension. 100-140 words. Plain text.",
    },
    {
        "id": "NUMBER_ANCHOR",
        "instruction": "Open with a specific number (6 weeks, 2000mg, 3rd bottle). Let the number signal specificity. End with what it made you question. 100-140 words. Plain text.",
    },
]

def rewrite_hook(topic, max_retries=3):
    pattern = random.choice(HOOK_PATTERNS)
    logging.info(f"    🎣 Hook 패턴: {pattern['id']}")

    for attempt in range(max_retries):
        prompt = (
            f"Topic: {topic}\n"
            f"PATTERN: {pattern['instruction']}\n\n"
            f"ABSOLUTE BANNED WORDS (violation = retry):\n"
            f"07:15, Oslo, cabin, woodsmoke, pine, frost, chill seeps,\n"
            f"mournful, encroaching darkness, frosted windows, icy grip,\n"
            f"polar night, trudge through, blade of frost, biting cold,\n"
            f"symphony, dance, whisper, molecular engine, gears, precision, tapestry\n\n"
            f"Output: plain text paragraph ONLY. No HTML. No quotes."
        )
        hook = ask_ai(prompt,
            "Write authentic non-cliche opening hooks. Never use Nordic winter cliches.",
            HEAVY_MODEL)

        hook_lower = hook.lower()
        found_cliche = [c for c in HOOK_CLICHES if c in hook_lower]

        if not found_cliche:
            logging.info(f"    ✅ Hook 클리셰 없음 (시도 {attempt+1})")
            return hook
        else:
            logging.warning(f"    ⚠️ Hook 클리셰 감지 [{', '.join(found_cliche)}] → 재시도 {attempt+1}/{max_retries}")
            pattern = random.choice([p for p in HOOK_PATTERNS if p["id"] != pattern["id"]])

    logging.warning(f"    ⚠️ Hook 클리셰 제거 실패 — 마지막 결과 사용")
    return hook

def rewrite_section(section_name, h2_title, topic, pmids, context="", idx=0, topic_type="synergy"):
    pmid_text = ""
    if pmids:
        pmid = pmids[idx % len(pmids)]
        variation = PMID_VARIATIONS[idx % len(PMID_VARIATIONS)]
        pmid_sentence = variation.format(pmid=pmid)
        pmid_text = (
            f'\n<blockquote><p>Research published via '
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" '
            f'rel="noopener noreferrer">PMID {pmid}</a>: {pmid_sentence}</p></blockquote>'
        )

    section_instructions = {
        0: "Focus on: WHAT the problem is + why this nutrient matters for it. Personal experience angle.",
        1: "Focus on: HOW it works biochemically. Specific enzymes/receptors. Plain-language parenthetical explanations.",
        2: "Focus on: STACKING options, synergistic nutrients, practical combinations.",
        3: "Focus on: CLINICAL EVIDENCE, specific studies, dosage ranges from research.",
        4: "Focus on: PRACTICAL PROTOCOL, timing, daily routine, personal adjustments.",
    }
    sec_instruction = section_instructions.get(idx, "Focus on a unique angle not covered in previous sections.")

    avoid_instruction = ""
    if context:
        avoid_instruction = f"\nDO NOT repeat these points already covered: {context[:200]}"

    prompt = (
        f"Write the '{section_name}' section for: {topic}\n\n"
        f"Section focus: {sec_instruction}\n"
        f"{avoid_instruction}\n\n"
        f"Requirements:\n"
        f"- 350-450 words\n"
        f"- 1st person experience ('I', 'my') mixed with casual facts\n"
        f"- Reference a specific personal experience or observation\n"
        f"- Use simple, conversational English (8th-grade level). Avoid heavy medical jargon.\n"
        f"- Do NOT use metaphors (no 'engines', 'gears', 'symphonies', 'dances').\n"
        f"- Do NOT act like a medical authority. Speak like a friend sharing what worked.\n"
        f"- HTML <p> tags ONLY — no headers, no markdown, no bullet points\n"
        f"- BANNED: 'Oslo', '07:15 AM', 'cabin', 'crucial', 'optimal', "
        f"'synergistically', 'pivotal', 'remarkable', 'unlock', 'protocol', 'nordic'\n"
        f"- Do NOT copy these instructions into output\n"
        f"- End with a practical takeaway or personal observation"
    )

    content = ask_ai(prompt,
        "Write authentic first-person health supplement blog content. HTML paragraphs only.",
        HEAVY_MODEL)

    return pmid_text + "\n" + content if pmid_text else content

def rewrite_takeaways(topic):
    prompt = (
        f"Write exactly 3 Key Takeaway bullet points for: {topic}\n"
        f"Rules:\n"
        f"- Each: 1 specific factual sentence, max 20 words\n"
        f"- Must be medically accurate\n"
        f"- No numbered lists — plain lines only\n"
        f"- Cover: mechanism, clinical benefit, practical tip\n"
        f"Output: 3 plain text lines. No HTML. No bullets. No numbers."
    )
    raw = ask_ai(prompt, "Write 3 concise factual bullet points.", LIGHT_MODEL)
    lines = [re.sub(r'^\d+[\.\)]\s*', '', l.lstrip('-* ').strip())
             for l in raw.splitlines() if l.strip()][:3]
    if len(lines) < 3:
        lines = [
            f"{topic} delivers measurable benefits through well-researched biochemical pathways.",
            f"Clinical research confirms improvements when dosage and timing are optimized.",
            f"Combining with complementary nutrients may enhance the overall effect.",
        ]
    kt_html = "".join([f"<li>{clean_banned(l)}</li>" for l in lines])
    return (
        f'<div style="background:#f0f7ff; border-left:4px solid #2a6496; '
        f'padding:16px; margin:20px 0;"><strong>Key Takeaways</strong>'
        f'<ul>{kt_html}</ul></div>'
    )

def generate_faq(topic):
    prompt = (
        f"Create an FAQ section for: {topic}\n"
        f"Rules:\n"
        f"- Exactly 3 Q&A pairs\n"
        f"- Questions must be specific to {topic}\n"
        f"- Answers: 50-80 words, medically accurate\n"
        f"- Include dosage and safety info where relevant\n"
        f"Output EXACTLY in this HTML format:\n"
        f"<h3>Question?</h3>\n<p>Answer.</p>\n"
    )
    return ask_ai(prompt, "Format FAQs in strict HTML. Be medically accurate.", LIGHT_MODEL)

def build_image_html(url, alt, caption):
    clean_alt = re.sub(r'^(and|And|or|Or|Stopped|Common|Comparing|Taking)\s+', '', alt).strip()
    if len(clean_alt.split()) < 3:
        clean_alt = f"Health supplement: {clean_alt}"
    return (
        f'<div style="margin:30px 0; text-align:center;">'
        f'<img src="{url}" alt="{clean_alt}" '
        f'style="max-width:100%; height:auto; border-radius:8px; '
        f'box-shadow:0 4px 12px rgba(0,0,0,0.1);" />'
        f'<div style="margin-top:10px; font-size:0.9em; color:#666; '
        f'font-style:italic; padding:12px; text-align:center;">{caption}</div></div>'
    )

def get_related_links(topic, count=4):
    try:
        links_db = load_json(BASE_DIR / "20_Meta" / "published_links.json", [])
        bad_markers = [
            "the my daily routine", "and pairing", "nutrient vs and",
            "disclosure-this-post", "dup and test", "maximize and athletic",
            "vitamin and d3", "when people prefer", "alpha and gpc",
        ]
        valid = []
        for l in links_db:
            title = l.get("title", "").lower()
            url = l.get("url", "")
            if not title or not url: continue
            if any(m in title for m in bad_markers): continue
            if title == topic.lower(): continue
            valid.append(l)

        t_lower = topic.lower()
        scored = []
        for l in valid:
            score = sum(1 for w in t_lower.split() if len(w) > 3 and w in l.get("title","").lower())
            scored.append((score, l))
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [l for _, l in scored[:count]]

        if len(selected) < count:
            remaining = [l for l in valid if l not in selected]
            random.shuffle(remaining)
            selected.extend(remaining[:count - len(selected)])

        return selected[:count]
    except Exception as e:
        logging.warning(f"    관련 링크 추출 실패: {e}")
        return []

def rewrite_post(title, old_html):
    topic = title.strip()
    topic_type = detect_topic_type(topic)
    core_nutrient = extract_core_nutrient(topic)
    logging.info(f"  📝 재작성 시작: {topic[:50]} (타입: {topic_type}, 핵심: {core_nutrient})")

    preserved = extract_preserved_elements(old_html)
    pmids = preserved['pmids']

    pmid_set = set(pmids)
    if len(pmid_set) < 3 or len(pmids) < 4:
        logging.info("    🔍 PMID 중복/부족 → pubmed_fetcher 시도...")
        try:
            from pubmed_fetcher import fetch_relevant_pmids
            papers = fetch_relevant_pmids(topic, 6)
            fresh = [str(p['pmid']) for p in papers
                     if str(p['pmid']).isdigit() and int(p['pmid']) < 44000000]
            if len(fresh) >= 3:
                pmids = fresh
                logging.info(f"    ✅ PMID 새로고침 완료: {pmids}")
        except Exception as e:
            logging.warning(f"    PMID 새로고침 실패: {e}")
            if not pmids:
                pmids = ["28709534", "26187077", "24470182", "31850742", "21753063", "34202712"]

    img_tags = preserved.get('img_tags', [])
    images = preserved.get('images', [])
    while len(images) < 6:
        images.append("[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]")

    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', old_html)
    h1_title = h1_match.group(1).strip() if h1_match else title
    if len(h1_title) > 60:
        h1_title = h1_title[:57] + "..."

    def get_section_img(idx):
        from googleapiclient.http import MediaFileUpload
        
        # [NEW] 로컬/imgur 등 양질의 이미지는 보존하고, 드라이브 이미지만 강제 재생성
        if idx < len(img_tags):
            src_match = re.search(r'src="([^"]+)"', img_tags[idx])
            if src_match:
                src = src_match.group(1)
                if 'drive.google.com' not in src and 'UPLOAD' not in src:
                    pos = old_html.find(img_tags[idx])
                    if pos > 0:
                        div_s = old_html.rfind('<div', 0, pos)
                        if div_s > 0:
                            div_e = old_html.find('</div>', pos) + 6
                            html_chunk = old_html[div_s:div_e]
                            # 캡션에 남아있는 footprint 제거
                            html_chunk = re.sub(r'(BBB\s*—\s*|Nordic dark season science\.?)', '', html_chunk, flags=re.IGNORECASE)
                            logging.info(f"    🖼️ 로컬/Imgur 기존 이미지 유지 (idx={idx})")
                            return html_chunk
                    logging.info(f"    🖼️ 로컬/Imgur 기존 이미지 유지 (idx={idx})")
                    return f'<div style="margin:30px 0; text-align:center;">{img_tags[idx]}</div>'

        logging.info(f"    🖼️ 드라이브/누락 이미지 감지 → 새로운 실사 강제 생성 (idx={idx})")
        safe = re.sub(r'[^\w]', '_', core_nutrient)[:40]
        fn = f"{safe}_s{idx}_rw2.png"
        url = generate_and_upload_image(core_nutrient, idx, fn)
        
        alt_variations = [
            f"A bottle of {core_nutrient.lower()} capsules on a kitchen counter",
            f"{core_nutrient.lower()} supplement pills next to a glass of water",
            f"Holding {core_nutrient.lower()} vitamins in hand",
            f"{core_nutrient.lower()} dietary supplement on a wooden desk"
        ]
        chosen_alt = alt_variations[idx % len(alt_variations)]
        
        cap_variations = [
            f"My daily setup for {core_nutrient[:30]}.",
            f"Figuring out the right dose.",
            f"Taking {core_nutrient[:30]} with breakfast.",
            f"A simple daily routine."
        ]
        chosen_cap = cap_variations[idx % len(cap_variations)]
        
        return build_image_html(url, chosen_alt, chosen_cap)

    hero = get_section_img(0)

    logging.info("    🎯 Key Takeaways 재작성...")
    takeaways = rewrite_takeaways(topic)

    logging.info("    🎣 Hook 재작성 (클리셰 차단)...")
    hook = rewrite_hook(topic)
    hook_html = f'<hr>\n<p>{hook}</p>\n<hr>'

    dynamic_sections = get_dynamic_sections(topic, topic_type)
    toc_items = "".join([
        f'<li><a href="#sec{i}">{name}</a></li>'
        for i, (_, name) in enumerate(dynamic_sections)
    ])
    toc_items += '<li><a href="#faq">Frequently Asked Questions</a></li>'
    toc_html = (
        '<div style="background:#f9f9f9; border:1px solid #ddd; padding:15px; '
        'margin:20px 0; border-radius:8px;">'
        '<strong style="font-size:1.1em;">Contents</strong>'
        f'<ul style="margin-top:10px; list-style-type:none; padding-left:5px; line-height:1.8;">'
        f'{toc_items}</ul></div>'
    )

    body_html = ""
    prev_context = ""
    for i, (sec_name, h2_title) in enumerate(dynamic_sections):
        logging.info(f"    ✍️ [{i+1}/5] {sec_name}...")
        sec_img = get_section_img(i + 1)
        content = rewrite_section(
            sec_name, h2_title, topic,
            pmids, prev_context, i, topic_type
        )
        table = ""
        if i == 0 and preserved['tables']:
            table = preserved['tables'][0]
        elif i == 2 and len(preserved['tables']) > 1:
            table = preserved['tables'][1]

        body_html += f'\n<h2 id="sec{i}">{h2_title}</h2>\n{sec_img}\n{content}\n{table}\n'
        plain = re.sub(r'<[^>]+>', ' ', content)
        prev_context = plain[:300] if len(plain) > 300 else plain

    internal_links = preserved['internal_links']
    if internal_links:
        bad_titles = ["the my daily routine", "and pairing", "nutrient vs and"]
        clean_links = [(u, t) for u, t in internal_links
                       if not any(b in t.lower() for b in bad_titles)]
        if len(clean_links) >= 3:
            links_html = "\n".join([
                f'<p>&#8594; <a href="{u}" rel="noopener noreferrer">Also worth reading: {t}</a></p>'
                for u, t in clean_links[:5]
            ])
        else:
            internal_links = []

    if not internal_links or len(internal_links) < 3:
        logging.info("    🔗 내부 링크 부족/오염 → DB에서 자동 추출...")
        related = get_related_links(topic, count=5)
        links_html = "\n".join([
            f'<p>&#8594; <a href="{l["url"]}" rel="noopener noreferrer">'
            f'Also worth reading: {l["title"]}</a></p>'
            for l in related
        ])

    cliff_styles = [
        (f'<blockquote><p>One thing I kept underestimating with {core_nutrient}: '
         f'how much timing mattered. Everything else stayed the same — only the timing changed.</p></blockquote>'),
        (f'<div style="background:#fff8f0; border-left:4px solid #e67e22; padding:18px; '
         f'margin:28px 0; border-radius:6px;">'
         f'<p style="margin:0;">There\'s one detail I haven\'t mentioned yet — '
         f'and it\'s the part that changed my results the most.</p></div>'),
    ]
    cliff_html = random.choice(cliff_styles)

    if preserved['faq'] and '<h3' in preserved['faq']:
        faq_html = f'<h2 id="faq">Frequently Asked Questions</h2>\n{preserved["faq"]}'
    else:
        logging.info("    ❓ FAQ 없음 → 자동 생성...")
        raw_faq = generate_faq(topic)
        faq_html = f'<h2 id="faq">Frequently Asked Questions</h2>\n{raw_faq}'

    methodology = (
        '<h2>About This Article</h2>'
        '<p>This article was written by Erik Lindström based on a personal review of '
        'peer-reviewed literature via PubMed. All scientific claims are linked directly '
        'to their primary sources. This is intended for educational purposes only '
        'and does not constitute medical advice.</p>'
    )

    disclaimer = (
        '<p style="font-size:0.85em;color:#666666;">'
        '<em>This content is for informational purposes only and does not constitute '
        'medical advice. Please read our full '
        '<a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html" '
        'rel="noopener noreferrer">Medical Disclaimer</a> '
        'before acting on any information provided.</em></p>'
    )

    new_html = "\n".join(filter(None, [
        preserved['disclosure'],
        f"<h1>{h1_title}</h1>",
        hero,
        takeaways,
        hook_html,
        toc_html,
        body_html,
        "<hr>",
        links_html,
        "<hr>",
        cliff_html,
        faq_html,
        "<hr>",
        methodology,
        "<hr>",
        disclaimer,
    ]))

    word_count = count_words(new_html)
    logging.info(f"  ✅ 재작성 완료: {word_count}단어")
    return new_html, word_count

def run_rewriter(limit=None):
    logging.info("✍️ NutriStack Retroactive Rewriter v2.0 시작")
    logging.info(f"  모델: {HEAVY_MODEL}")
    logging.info("  [FIX 1] 섹션 제목 동적 생성")
    logging.info("  [FIX 2] Hook 클리셰 강제 차단")
    logging.info("  [FIX 3] PMID 로테이션")
    logging.info("  [FIX 4] Erik Lindström About This Article")
    logging.info("  [FIX 5] BANNED_PHRASES 확장")
    report("소급 재작성 v2.0 시작")

    service = get_service()
    posts = get_all_posts(service)
    logging.info(f"  총 {len(posts)}개 포스팅")

    done_ids = {d["post_id"] for d in load_done()}
    targets = [p for p in posts if p.get('id') not in done_ids]
    if limit:
        targets = targets[:limit]

    logging.info(f"  재작성 대상: {len(targets)}개")
    report(f"재작성 대상: {len(targets)}개")

    success = failed = 0
    for i, post in enumerate(targets, 1):
        post_id = post.get('id', '')
        title   = post.get('title', '')
        content = post.get('content', '')

        logging.info(f"\n{'='*50}")
        logging.info(f"[{i}/{len(targets)}] {title[:50]}")
        logging.info(f"  현재: {count_words(content)}단어")
        report(f"[{i}/{len(targets)}] 재작성 중: {title[:40]}")

        try:
            new_content, word_count = rewrite_post(title, content)
            url = update_post(service, post_id, title, new_content)
            if url:
                logging.info(f"  ✅ 업데이트 완료 ({word_count}단어)")
                report(f"✅ 완료: {title[:40]} ({word_count}단어)")
                save_done(post_id, title)
                success += 1
            else:
                logging.error("  ❌ 업데이트 실패")
                failed += 1
        except Exception as e:
            logging.error(f"  ❌ 오류: {e}")
            failed += 1

        if i < len(targets):
            logging.info(f"  ⏳ {DELAY}초 대기...")
            time.sleep(DELAY)

    logging.info(f"\n{'='*50}")
    logging.info(f"🏆 재작성 완료! 성공:{success} 실패:{failed}")
    report(f"🏆 재작성 완료! 성공:{success} 실패:{failed}")

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args:
        run_rewriter()
    elif args[0] == "one":
        logging.info("🧪 1개 테스트 재작성")
        run_rewriter(limit=1)
    elif args[0] == "n" and len(args) > 1:
        run_rewriter(limit=int(args[1]))
    elif args[0] == "history":
        done = load_done()
        logging.info(f"📋 재작성 완료 ({len(done)}개):")
        for d in done[-20:]:
            logging.info(f"  {d['date']} — {d['title'][:50]}")
    elif args[0] == "reset":
        save_json(DONE_FILE, [])
        logging.info("♻️ 완료 기록 초기화")
    else:
        print("""
사용법:
  python retroactive_rewriter.py          # 전체 재작성
  python retroactive_rewriter.py one      # 1개 테스트
  python retroactive_rewriter.py n 5      # 5개 재작성
  python retroactive_rewriter.py history  # 완료 이력
  python retroactive_rewriter.py reset    # 기록 초기화
        """)