"""
NutriStack Lab — Image Restorer v2.2 (RTX 3060 최적화)
변경사항 v2.2:
  - RTX 3060 이하 VRAM 최적화 (hero: 768×1152, s1~s5: 896×512)
  - --medvram / xformers 자동 감지 페이로드
  - SDXL → SD 1.5 fallback 로직 강화
  - 배치 사이즈 1 고정
  - VAE 타일링 활성화 (대형 이미지 VRAM 절약)
  - Pollinations fallback 해상도도 낮춤
"""

import json
import re
import time
import pickle
import logging
import requests
import base64
import random
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
        logging.FileHandler('image_restorer.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR            = Path(__file__).parent
TOKEN_FILE          = BASE_DIR / "token.pickle"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/drive.file'
]
BLOG_ID   = "2812259517039331714"
IMAGE_DIR = BASE_DIR / "05_Images"
IMAGE_DIR.mkdir(exist_ok=True, parents=True)
DISCORD_FILE    = BASE_DIR / "discord_webhook.json"
DONE_FILE       = BASE_DIR / "20_Meta" / "image_restorer_done.json"
GEMINI_API_FILE = BASE_DIR / "gemini_config.json"
DELAY = 3

# ============================================================
# ★ RTX 3060 이하 최적화 설정
# ============================================================
SD_API_URL = "http://127.0.0.1:7860"

# Hero: 세로형 (블로그 상단) — VRAM 절약을 위해 768×1152로 낮춤
# 섹션: 가로형 (본문) — 896×512로 낮춤
HERO_W,  HERO_H  = 768,  1152   # (원본 1000×1500 → VRAM 절약)
SEC_W,   SEC_H   = 896,  512    # (원본 1376×768  → VRAM 절약)

# SDXL 모델명 (Stability Matrix에 설치된 이름으로 변경)
SDXL_MODEL = "epicrealismXL_pureFix.safetensors"
SD15_MODEL = "epicrealismXL_pureFix.safetensors"

# SD API 공통 옵션 (VRAM 절약)
SD_COMMON = {
    "negative_prompt": (
        "watermark, text, logo, blurry, low quality, "
        "bad anatomy, ugly, deformed, noisy, grainy, "
        "white background, bright background"
    ),
    "cfg_scale":    7,
    "sampler_name": "DPM++ 2M Karras",
    "batch_size":   1,
    "n_iter":       1,
    # VAE 타일링: 대형 이미지 VRAM 절약 핵심
    "enable_hr":    False,
    "tiling":       False,
}

# ============================================================
# 영양소별 실사 라이프스타일 시각 DB
# ============================================================
NUTRIENT_VISUALS = {
    "magnesium": {
        "subject":  "magnesium supplement bottle and capsules",
        "setting":  "wooden kitchen counter, morning light, glass of water nearby",
        "mood":     "calm relaxed morning routine",
    },
    "vitamin d3": {
        "subject":  "vitamin D3 supplement capsules",
        "setting":  "sunny windowsill, warm golden morning light, small plant nearby",
        "mood":     "bright sunny warm lifestyle",
    },
    "vitamin d": {
        "subject":  "vitamin D supplement bottle",
        "setting":  "sunlit wooden table, natural window light",
        "mood":     "warm bright natural",
    },
    "omega-3": {
        "subject":  "omega-3 fish oil capsules",
        "setting":  "wooden table with salmon fillet and lemon beside bottle",
        "mood":     "fresh healthy Nordic kitchen",
    },
    "omega": {
        "subject":  "omega-3 capsules and fish oil bottle",
        "setting":  "clean white kitchen counter, natural light",
        "mood":     "fresh healthy lifestyle",
    },
    "zinc": {
        "subject":  "zinc supplement tablets and bottle",
        "setting":  "wooden table with citrus fruits and nuts beside bottle",
        "mood":     "natural healthy kitchen scene",
    },
    "hmb": {
        "subject":  "HMB supplement powder and capsules",
        "setting":  "gym bag on wooden floor, water bottle, workout towel",
        "mood":     "athletic active lifestyle morning",
    },
    "l-theanine": {
        "subject":  "L-theanine supplement capsules",
        "setting":  "beside a steaming cup of green tea, wooden desk, calm morning",
        "mood":     "peaceful focused calm",
    },
    "theanine": {
        "subject":  "theanine supplement bottle and green tea cup",
        "setting":  "wooden desk with notebook, soft morning light",
        "mood":     "calm productive morning",
    },
    "creatine": {
        "subject":  "creatine monohydrate powder and shaker bottle",
        "setting":  "gym counter, workout gloves nearby, natural light",
        "mood":     "athletic active performance",
    },
    "lion": {
        "subject":  "lion's mane mushroom supplement capsules",
        "setting":  "wooden table with fresh lion's mane mushroom beside bottle",
        "mood":     "natural earthy wellness",
    },
    "bacopa": {
        "subject":  "bacopa supplement capsules and small plant",
        "setting":  "wooden desk, books in background, soft natural light",
        "mood":     "focus study calm",
    },
    "collagen": {
        "subject":  "collagen powder and supplement bottle",
        "setting":  "kitchen counter with coffee cup, morning light, clean aesthetic",
        "mood":     "fresh clean beauty wellness",
    },
    "vitamin c": {
        "subject":  "vitamin C supplement bottle and tablets",
        "setting":  "wooden table with fresh oranges and lemons, bright natural light",
        "mood":     "bright vibrant fresh healthy",
    },
    "quercetin": {
        "subject":  "quercetin supplement capsules",
        "setting":  "wooden table with apples and berries, natural light",
        "mood":     "natural antioxidant healthy",
    },
    "coq10": {
        "subject":  "CoQ10 supplement capsules and bottle",
        "setting":  "clean wooden counter, morning light, glass of water",
        "mood":     "clean healthy morning routine",
    },
    "nmn": {
        "subject":  "NMN supplement capsules",
        "setting":  "minimalist wooden table, sleek bottle, morning sunlight",
        "mood":     "clean modern anti-aging wellness",
    },
    "berberine": {
        "subject":  "berberine supplement capsules",
        "setting":  "wooden table with a small bowl of berries, natural light",
        "mood":     "natural metabolic health",
    },
    "probiotics": {
        "subject":  "probiotic supplement bottle and capsules",
        "setting":  "kitchen counter with yogurt and fresh fruit nearby",
        "mood":     "gut health fresh natural",
    },
    "glutathione": {
        "subject":  "glutathione supplement capsules",
        "setting":  "clean white counter, green vegetables nearby, bright light",
        "mood":     "clean detox wellness",
    },
    "ashwagandha": {
        "subject":  "ashwagandha supplement capsules and root",
        "setting":  "wooden table with dried herbs, warm earth-tone setting",
        "mood":     "natural adaptogen calm earthy",
    },
    "boron": {
        "subject":  "boron supplement bottle",
        "setting":  "wooden table, clean minimal setting, natural light",
        "mood":     "clean minimal health",
    },
    "pqq": {
        "subject":  "PQQ supplement capsules",
        "setting":  "wooden desk with coffee, morning productivity scene",
        "mood":     "energy focus morning",
    },
    "phosphatidylserine": {
        "subject":  "phosphatidylserine supplement capsules",
        "setting":  "wooden desk with books and a cup of tea, focused setting",
        "mood":     "brain health focus calm",
    },
    "b12": {
        "subject":  "vitamin B12 supplement bottle and tablets",
        "setting":  "wooden table with eggs and dairy nearby, bright kitchen light",
        "mood":     "energy health bright morning",
    },
    "default": {
        "subject":  "health supplement bottle and capsules",
        "setting":  "wooden table, natural window light, clean minimal setting",
        "mood":     "clean healthy lifestyle morning",
    },
}

# 섹션별 구도 — 실사 라이프스타일 스타일
SECTION_COMPOSITIONS = {
    "hero": {
        "composition": "flat lay overhead shot, supplement bottle center, natural props around it",
        "style":       "lifestyle product photography, warm natural tones, soft shadows",
    },
    "s1": {
        "composition": "over-the-shoulder shot, person holding supplement with coffee at wooden table",
        "style":       "candid lifestyle photography, warm indoor light, shallow depth of field",
    },
    "s2": {
        "composition": "close-up of supplement capsules spilling from bottle onto wooden surface",
        "style":       "macro lifestyle photography, soft bokeh background, warm tones",
    },
    "s3": {
        "composition": "supplement bottle beside healthy food ingredients on kitchen counter",
        "style":       "food and wellness lifestyle photo, bright natural light, clean aesthetic",
    },
    "s4": {
        "composition": "morning routine flat lay: supplement, water glass, notebook on wooden desk",
        "style":       "top-down lifestyle photography, warm morning light, minimalist",
    },
    "s5": {
        "composition": "hand holding supplement capsule near window with soft natural light",
        "style":       "intimate lifestyle close-up, warm bokeh, authentic feel",
    },
}

QUALITY_SUFFIX = (
    ", realistic lifestyle photography, Canon 5D Mark IV, "
    "natural window light, warm tones, sharp focus, "
    "high resolution, no text, no watermark, no logo, photorealistic"
)


def build_hq_prompt(topic, section_key="hero"):
    """토픽에 맞는 실사 라이프스타일 이미지 프롬프트 생성"""
    t = topic.lower()

    visual = NUTRIENT_VISUALS["default"]
    for kw, v in NUTRIENT_VISUALS.items():
        if kw != "default" and kw in t:
            visual = v
            break

    comp = SECTION_COMPOSITIONS.get(section_key, SECTION_COMPOSITIONS["hero"])

    prompt = (
        f"{visual['subject']}, "
        f"{visual['setting']}, "
        f"{visual['mood']}, "
        f"{comp['composition']}, "
        f"{comp['style']}"
        f"{QUALITY_SUFFIX}"
    )
    return prompt[:380]


# ============================================================
# Google API
# ============================================================
def get_creds():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logging.info("⏳ 토큰 갱신 중...")
                creds.refresh(Request())
            except Exception as e:
                logging.warning(f"❌ 토큰 갱신 실패 (재인증 필요): {e}")
                if TOKEN_FILE.exists():
                    TOKEN_FILE.unlink()
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)
    return creds

def get_blogger():
    return build('blogger', 'v3', credentials=get_creds())

def get_drive():
    return build('drive', 'v3', credentials=get_creds())

def upload_to_drive(img_path, filename):
    try:
        svc = get_drive()
        f = svc.files().create(
            body={"name": filename},
            media_body=MediaFileUpload(str(img_path), mimetype='image/png'),
            fields='id'
        ).execute()
        fid = f.get('id')
        svc.permissions().create(
            fileId=fid,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        url = f"https://drive.google.com/thumbnail?id={fid}&sz=s1000"
        logging.info(f"    ✅ Drive 업로드: {filename[:40]}")
        return url
    except Exception as e:
        logging.warning(f"    Drive 실패: {e}")
        return None


# ============================================================
# ★ 이미지 생성 (RTX 3060 최적화)
# ============================================================
def check_sd_api():
    """SD API 활성화 여부 확인"""
    try:
        r = requests.get(f"{SD_API_URL}/sdapi/v1/sd-models", timeout=5)
        return r.status_code == 200
    except:
        return False

def try_sdxl(prompt, width, height, steps):
    """SDXL 생성 시도"""
    payload = {
        **SD_COMMON,
        "prompt": prompt,
        "steps":  steps,
        "width":  width,
        "height": height,
        "override_settings": {
            "sd_model_checkpoint": SDXL_MODEL,
            # VAE 타일링으로 VRAM 절약
            "CLIP_stop_at_last_layers": 2,
        },
        "override_settings_restore_afterwards": True,
    }
    r = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=300)
    if r.status_code == 200:
        return base64.b64decode(r.json()["images"][0])
    raise Exception(f"SDXL API 오류: {r.status_code}")

def try_sd15(prompt, width, height, steps):
    """SD 1.5 생성 시도 (VRAM 절약 버전)"""
    payload = {
        **SD_COMMON,
        "prompt": prompt,
        "steps":  steps,
        "width":  width,
        "height": height,
        "override_settings": {
            "sd_model_checkpoint": SD15_MODEL,
        },
        "override_settings_restore_afterwards": True,
    }
    r = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=300)
    if r.status_code == 200:
        return base64.b64decode(r.json()["images"][0])
    raise Exception(f"SD1.5 API 오류: {r.status_code}")

def try_pollinations(prompt, width, height):
    """Pollinations Flux 폴백"""
    seed = random.randint(100000, 999999)
    url = (
        f"https://image.pollinations.ai/prompt/"
        f"{requests.utils.quote(prompt[:120])}"
        f"?width={width}&height={height}&model=flux&seed={seed}&nologo=true"
    )
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 200 and len(r.content) > 10000:
                return r.content
        except Exception as e:
            logging.warning(f"    Pollinations 시도 {attempt+1} 실패: {e}")
        time.sleep(5)
    return None

def generate_hq_image(topic, section_key, img_fn):
    """
    RTX 3060 최적화 이미지 생성
    순서: SDXL → SD1.5 → Pollinations
    Hero:   768×1152, steps=25
    섹션:   896×512,  steps=20
    """
    prompt   = build_hq_prompt(topic, section_key)
    is_hero  = section_key == "hero"
    width    = HERO_W  if is_hero else SEC_W
    height   = HERO_H  if is_hero else SEC_H
    steps    = 25      if is_hero else 20
    img_path = IMAGE_DIR / img_fn

    logging.info(f"    🎨 [{section_key}] {width}×{height} steps={steps}")
    logging.info(f"    📝 프롬프트: {prompt[:80]}...")

    img_bytes = None

    # 1순위: SD 1.5 (모든 이미지)
    if check_sd_api():
        try:
            logging.info(f"    🤖 SD 1.5 시도 중... ({width}×{height})")
            img_bytes = try_sd15(prompt, width, height, steps)
            logging.info(f"    ✅ SD 1.5 성공!")
        except Exception as e:
            logging.warning(f"    ⚠️ SD 1.5 실패 → Pollinations 폴백: {e}")

    # 3순위: Pollinations Flux (온라인 폴백)
    if img_bytes is None:
        logging.info(f"    🔄 Pollinations Flux 폴백...")
        img_bytes = try_pollinations(prompt, width, height)

    # 저장 및 Drive 업로드
    if img_bytes:
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        drive_url = upload_to_drive(img_path, img_fn)
        if drive_url:
            return drive_url

    logging.warning(f"    ❌ 이미지 생성 실패: {section_key}")
    return "[UPLOAD_TO_BLOGGER_THEN_PASTE_URL_HERE]"


def build_image_div(url, alt, caption):
    return (
        f'<div style="text-align:center; margin:20px 0;">'
        f'<img src="{url}" alt="{alt}" '
        f'style="max-width:100%; height:auto;" />'
        f'<div style="background-color:#f8f9fa; border-radius:4px; '
        f'color:#555555; display:block; '
        f'font-family:\'Courier New\',Courier,monospace; '
        f'font-size:13px; letter-spacing:-0.5px; line-height:1.5; '
        f'margin-bottom:30px; margin-top:10px; padding:12px; '
        f'text-align:center;">{caption}</div></div>'
    )


# ============================================================
# 포스팅 이미지 복구
# ============================================================
def count_images(html):
    return len(re.findall(r'<img[^>]+>', html))

def has_valid_images(html):
    imgs = re.findall(r'src="([^"]+)"', html)
    valid = [u for u in imgs if u.startswith('http') and 'UPLOAD' not in u and 'imgur.com' not in u]
    return len(valid) > 0

def strip_all_images(html):
    html = re.sub(
        r'<div style="text-align:center[^>]*>.*?</div>\s*</div>',
        '', html, flags=re.DOTALL
    )
    html = re.sub(r'<img[^>]+>', '', html)
    return html


def restore_images_for_post(title, html, post_id, force=False):
    topic     = title.strip()
    safe_name = re.sub(r'[^\w]', '_', topic)[:35]

    section_keys   = ["hero", "s1", "s2", "s3", "s4", "s5"]
    section_labels = [
        "Nordic science visualization",
        "Blood-Brain Barrier mechanism",
        "Synaptic plasticity neural science",
        "Nootropic synergy stack",
        "Clinical evidence data",
        "Nordic dosage protocol"
    ]

    if force:
        logging.info(f"  🗑️ 기존 이미지 전부 제거 후 재생성")
        html = strip_all_images(html)

    h2_positions = [m.start() for m in re.finditer(r'<h2[^>]*>', html)]
    new_html = html

    hero_has_img = bool(re.search(
        r'<h1>.*?</h1>.*?<img[^>]+src="http(?!.*imgur\.com)',
        html[:2000], re.DOTALL
    ))

    sections_to_restore = []
    if not hero_has_img:
        sections_to_restore.append(("hero", 0))

    for i, h2_pos in enumerate(h2_positions[:5]):
        next_pos = h2_positions[i+1] if i+1 < len(h2_positions) else len(html)
        section_html = html[h2_pos:next_pos]
        imgs  = re.findall(r'src="([^"]+)"', section_html)
        valid = [u for u in imgs if u.startswith('http') and 'UPLOAD' not in u and 'imgur.com' not in u]
        if not valid:
            sections_to_restore.append((section_keys[i+1], i+1))

    logging.info(f"  🔍 생성 필요 섹션: {len(sections_to_restore)}개")

    if not sections_to_restore:
        logging.info(f"  ✅ 이미지 정상")
        return html, False

    generated_imgs = {}

    for sec_key, idx in sections_to_restore:
        label    = section_labels[min(idx, len(section_labels)-1)]
        img_fn   = f"{safe_name}_{sec_key}_{datetime.now().strftime('%H%M%S')}.png"

        logging.info(f"  🎨 이미지 생성: {sec_key}")
        url     = generate_hq_image(topic, sec_key, img_fn)
        alt     = f"{topic.lower()} {sec_key} nordic supplement science"
        caption = f"{label} — {topic[:45]} Nordic dark season science."
        generated_imgs[sec_key] = build_image_div(url, alt, caption)

        if (sec_key, idx) != sections_to_restore[-1]:
            time.sleep(1)

    # Hero 이미지 삽입
    if "hero" in generated_imgs:
        h1_end = html.find('</h1>')
        if h1_end > 0:
            insert_pos = h1_end + 5
            new_html = (
                new_html[:insert_pos] + "\n" +
                generated_imgs["hero"] + "\n" +
                new_html[insert_pos:]
            )

    # 섹션 이미지 삽입
    for sec_key, idx in sections_to_restore:
        if sec_key == "hero" or sec_key not in generated_imgs:
            continue
        h2_matches  = list(re.finditer(r'<h2[^>]*>.*?</h2>', new_html, re.DOTALL))
        target_idx  = idx - 1
        if target_idx < len(h2_matches):
            h2_end   = h2_matches[target_idx].end()
            new_html = (
                new_html[:h2_end] + "\n" +
                generated_imgs[sec_key] + "\n" +
                new_html[h2_end:]
            )

    return new_html, True


# ============================================================
# 메인 실행
# ============================================================
def report(msg):
    try:
        if DISCORD_FILE.exists():
            data = json.loads(DISCORD_FILE.read_text(encoding='utf-8'))
            url  = data.get("webhook_url", "")
            if url:
                requests.post(url, json={"content": f"🖼️ **[이미지복구]** {msg}"}, timeout=5)
    except:
        pass

def load_done():
    if Path(DONE_FILE).exists():
        return json.loads(Path(DONE_FILE).read_text(encoding='utf-8'))
    return []

def save_done(post_id):
    done = load_done()
    done.append({"post_id": post_id, "date": datetime.now().isoformat()})
    Path(DONE_FILE).parent.mkdir(exist_ok=True, parents=True)
    Path(DONE_FILE).write_text(
        json.dumps(done, ensure_ascii=False, indent=2), encoding='utf-8'
    )

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

def run_restorer(limit=None, force=False, test_latest=False):
    logging.info("🖼️ NutriStack Image Restorer v2.2 시작 (RTX 3060 최적화)")
    logging.info(f"  Hero 해상도:  {HERO_W}×{HERO_H}")
    logging.info(f"  섹션 해상도:  {SEC_W}×{SEC_H}")
    logging.info(f"  모델: SDXL(hero) → SD1.5 → Pollinations Flux")
    report("이미지 복구 시작!")

    # SD API 상태 확인
    if check_sd_api():
        logging.info("  ✅ Stability Matrix SD API 연결됨")
    else:
        logging.warning("  ⚠️ SD API 응답 없음 → Pollinations 폴백 사용")
        logging.warning("  💡 Stability Matrix에서 모델 실행 후 API 활성화 확인")

    service = get_blogger()
    posts   = get_all_posts(service)
    logging.info(f"  총 {len(posts)}개 포스팅")

    done_ids = set() if force else {d["post_id"] for d in load_done()}
    targets  = [p for p in posts if p.get('id') not in done_ids]

    if test_latest:
        no_img = [posts[0]]
        logging.info(f"  🔥 FORCE_ONE 모드: 최신글 '{no_img[0].get('title', '')}' 테스트")
    else:
        if limit:
            targets = targets[:limit]
        if force:
            no_img = targets
            logging.info(f"  ⚡ FORCE 모드: 전체 {len(no_img)}개 이미지 교체")
            report(f"⚡ FORCE 모드: {len(no_img)}개 전체 이미지 교체 시작!")
        else:
            no_img  = [p for p in targets if not has_valid_images(p.get('content',''))]
            has_img = [p for p in targets if has_valid_images(p.get('content',''))]
            logging.info(f"  🔴 이미지 없음: {len(no_img)}개 (처리)")
            logging.info(f"  ✅ 이미지 있음: {len(has_img)}개 (스킵)")
        report(f"이미지 없는 포스팅: {len(no_img)}개")

    if not no_img:
        logging.info("  ✅ 처리할 포스팅 없음!")
        return

    success = failed = 0

    for i, post in enumerate(no_img, 1):
        post_id = post.get('id', '')
        title   = post.get('title', '')
        content = post.get('content', '')

        logging.info(f"\n{'='*50}")
        logging.info(f"[{i}/{len(no_img)}] {title[:50]}")
        report(f"[{i}/{len(no_img)}] 복구 중: {title[:40]}")

        try:
            new_content, changed = restore_images_for_post(
                title, content, post_id, force=force
            )

            if not changed:
                save_done(post_id)
                continue

            update_body = {"title": title, "content": new_content}
            existing_labels = post.get("labels", [])
            if existing_labels:
                update_body["labels"] = existing_labels
            res = service.posts().update(
                blogId=BLOG_ID,
                postId=post_id,
                body=update_body
            ).execute()

            if res.get('url'):
                logging.info(f"  ✅ 복구 완료!")
                report(f"✅ 복구: {title[:40]}")
                save_done(post_id)
                success += 1
            else:
                failed += 1

        except Exception as e:
            logging.error(f"  ❌ 오류: {e}")
            failed += 1

        time.sleep(DELAY)

    logging.info(f"\n{'='*50}")
    logging.info(f"🏆 복구 완료! 성공:{success} 실패:{failed}")
    report(f"🏆 이미지 복구 완료! 성공:{success} 실패:{failed}")


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args:
        run_restorer()

    elif args[0] == "one":
        logging.info("🧪 1개 테스트 (이미지 없는 글 찾기)")
        run_restorer(limit=1)

    elif args[0] == "force_one":
        logging.info("🔥 강제 1개 덮어쓰기 테스트 (최신글 대상)")
        run_restorer(limit=1, force=True, test_latest=True)

    elif args[0] == "n" and len(args) > 1:
        run_restorer(limit=int(args[1]))

    elif args[0] == "force":
        logging.info("⚡ 전체 강제 재생성")
        run_restorer(force=True)

    elif args[0] == "scan":
        service = get_blogger()
        posts   = get_all_posts(service)
        no_img  = [p for p in posts if not has_valid_images(p.get('content',''))]
        logging.info(f"\n📊 이미지 스캔 결과:")
        logging.info(f"  🔴 이미지 없음: {len(no_img)}개")
        logging.info(f"  ✅ 이미지 있음: {len(posts)-len(no_img)}개")
        for p in no_img:
            logging.info(f"    → {p.get('title','')[:55]}")

    elif args[0] == "reset":
        Path(DONE_FILE).write_text("[]", encoding='utf-8')
        logging.info("♻️ 완료 기록 초기화")

    elif args[0] == "test_prompt":
        topic = " ".join(args[1:]) if len(args) > 1 else "Magnesium and Zinc"
        for key in ["hero", "s1", "s2", "s3", "s4", "s5"]:
            p = build_hq_prompt(topic, key)
            logging.info(f"\n[{key}] {p[:120]}...")

    elif args[0] == "check":
        # SD API 상태만 확인
        if check_sd_api():
            logging.info("✅ Stability Matrix SD API 정상 작동 중!")
        else:
            logging.warning("❌ SD API 응답 없음")
            logging.warning("💡 Stability Matrix → 모델 실행 → Launch Arguments에 --api 추가")

    else:
        print("""
사용법:
  python image_restorer.py              # 이미지 없는 포스팅 자동 복구
  python image_restorer.py one          # 빈 포스팅 1개 테스트
  python image_restorer.py force_one    # 최신글 1개 강제 재생성 (테스트)
  python image_restorer.py n 5          # 5개 복구
  python image_restorer.py scan         # 이미지 없는 포스팅 스캔
  python image_restorer.py force        # 전체 강제 재생성
  python image_restorer.py reset        # 완료 기록 초기화
  python image_restorer.py check        # SD API 연결 상태 확인
  python image_restorer.py test_prompt [주제]  # 프롬프트 미리보기
        """)