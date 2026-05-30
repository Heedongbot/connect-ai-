"""
regen_elderberry_images.py
Elderberry and Zinc Synergy 포스트 이미지 재생성
epicrealismXL (SD1.5) → Imgur 업로드 → 체크포인트 + 예약 포스트 업데이트
"""

import base64, json, re, pickle, requests, time, logging
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_ID    = "5651926965473076106"
IMAGE_DIR  = BASE_DIR / "05_Images"
CHK_FILE   = BASE_DIR / "02_Checkpoints" / "[REWRITE]_Elderberry_and_Zinc_Synergy.json"
IMGUR_CID  = "546c25a59c58ad7"
SD_URL     = "http://127.0.0.1:7860"
SD_MODEL   = "epicrealismXL_pureFix.safetensors"

NEGATIVE = (
    "molecule, diagram, scientific visualization, 3d render, cgi, cartoon, illustration, "
    "painting, aurora, abstract, dark background, neon, cyberpunk, text, watermark, logo, "
    "blurry, low quality, deformed, ugly, extra limbs, face close-up, oversaturated, "
    "cell, dna, atom, chemistry, lab equipment"
)

REALISM_SUFFIX = (
    "realistic lifestyle photography, Canon 5D Mark IV, natural light, warm tones, "
    "sharp focus, high resolution, no text, no watermark, photorealistic"
)

# 이미지별 프롬프트 (실사 라이프스타일)
IMAGE_PROMPTS = {
    "hero": (
        "Elderberry gummies and zinc supplement bottle on a rustic wooden kitchen counter, "
        "fresh elderberries scattered nearby, small glass of water, morning sunlight from window, "
        "warm golden tones, styled flat lay, vertical composition, "
        + REALISM_SUFFIX
    ),
    "s1": (
        "Close-up of a hand holding two supplement capsules, one dark purple elderberry, one zinc, "
        "over a kitchen table with coffee mug, soft natural window light, "
        "health morning routine, "
        + REALISM_SUFFIX
    ),
    "s2": (
        "Elderberry syrup bottle and zinc supplement jar next to a bowl of fresh blueberries "
        "and honey on a marble kitchen counter, natural daylight, clean minimalist styling, "
        + REALISM_SUFFIX
    ),
    "s3": (
        "Weekly pill organizer with elderberry and zinc supplements on a wooden nightstand, "
        "soft lamp light, journal and pen beside it, cozy home bedroom background, "
        "health tracking routine, "
        + REALISM_SUFFIX
    ),
}

IMAGE_SIZES = {
    "hero": (768, 1152),
    "s1":   (896, 512),
    "s2":   (896, 512),
    "s3":   (896, 512),
}


def sd_generate(prompt: str, is_hero: bool) -> bytes | None:
    width, height = (768, 1152) if is_hero else (896, 512)
    payload = {
        "prompt": prompt,
        "negative_prompt": NEGATIVE,
        "steps": 26 if is_hero else 22,
        "width": width,
        "height": height,
        "cfg_scale": 6.5,
        "sampler_name": "DPM++ 2M Karras",
        "override_settings": {"sd_model_checkpoint": SD_MODEL},
    }
    try:
        r = requests.post(f"{SD_URL}/sdapi/v1/txt2img", json=payload, timeout=300)
        r.raise_for_status()
        return base64.b64decode(r.json()["images"][0])
    except Exception as e:
        logging.error(f"  SD 실패: {e}")
        return None


def upload_imgur(img_path: Path) -> str | None:
    try:
        b64 = base64.b64encode(img_path.read_bytes()).decode()
        r = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": f"Client-ID {IMGUR_CID}"},
            data={"image": b64, "type": "base64"},
            timeout=30,
        )
        if r.status_code == 200:
            url = r.json()["data"]["link"]
            logging.info(f"  Imgur OK: {img_path.name} -> {url}")
            return url
    except Exception as e:
        logging.warning(f"  Imgur 실패: {e}")
    return None


def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def build_img_html(url: str, alt: str, caption: str) -> str:
    clean_alt = re.sub(r'(?i)^(and|or)\s+', '', alt).strip()
    if len(clean_alt.split()) < 3:
        clean_alt = f"Health supplement routine: {clean_alt}"
    return (
        f'<div class="img-container">'
        f'<img src="{url}" alt="{clean_alt}" />'
        f'<div class="img-caption">{caption}</div></div>'
    )


def run():
    new_images = {}

    # 1. 이미지 생성 + 업로드
    for key, prompt in IMAGE_PROMPTS.items():
        logging.info(f"\n{'='*50}\n[{key}] 생성 중...")
        logging.info(f"  prompt: {prompt[:80]}...")

        is_hero = key == "hero"
        img_bytes = sd_generate(prompt, is_hero)

        if img_bytes:
            fn = f"Elderberry_Zinc_Synergy_{key}_new.png"
            img_path = IMAGE_DIR / fn
            img_path.write_bytes(img_bytes)
            logging.info(f"  SD 생성 완료 ({len(img_bytes):,} bytes)")
        else:
            logging.warning(f"  SD 실패 — Pollinations 폴백 사용")
            w, h = IMAGE_SIZES[key]
            poll_url = (
                f"https://image.pollinations.ai/prompt/"
                f"{requests.utils.quote(prompt[:120])}"
                f"?width={w}&height={h}&model=flux&nologo=true"
            )
            fn = f"Elderberry_Zinc_Synergy_{key}_new.png"
            img_path = IMAGE_DIR / fn
            for _ in range(3):
                try:
                    r = requests.get(poll_url, timeout=60)
                    if r.status_code == 200 and len(r.content) > 5000:
                        img_path.write_bytes(r.content)
                        logging.info(f"  Pollinations OK ({len(r.content):,} bytes)")
                        break
                except Exception as e:
                    logging.warning(f"  Pollinations 시도 실패: {e}")
                time.sleep(2)

        # Imgur 업로드
        url = upload_imgur(img_path)
        if url:
            new_images[key] = url
        else:
            logging.error(f"  [{key}] Imgur 업로드 실패")
        time.sleep(1)

    if not new_images.get("hero"):
        logging.error("Hero 이미지 없음 — 중단")
        return

    logging.info(f"\n생성 완료: {list(new_images.keys())}")

    # 2. 체크포인트 업데이트
    data = json.loads(CHK_FILE.read_text(encoding="utf-8"))
    data["images"].update(new_images)
    CHK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("체크포인트 이미지 업데이트 완료")

    # 3. 예약 포스트 HTML에서 이미지 URL 교체
    svc = get_service()
    result = svc.posts().list(blogId=BLOG_ID, status=["SCHEDULED"], maxResults=5).execute()
    post = None
    for p in result.get("items", []):
        if p["id"] == POST_ID:
            post = p
            break

    if not post:
        logging.error("예약 포스트 없음")
        return

    html = post.get("content", "")
    title = post.get("title", "")
    labels = post.get("labels", [])

    # 기존 Imgur URL을 새 URL로 교체
    old_images = data.get("images", {})  # 이미 업데이트됨
    # 원본 이전 URL들 (체크포인트 업데이트 전 값)
    original_urls = {
        "hero": "https://i.imgur.com/K456ixW.png",
        "s1":   "https://i.imgur.com/BN1Ex0u.png",
        "s2":   "https://i.imgur.com/spKa5n8.png",
        "s3":   "https://i.imgur.com/VEp4ExF.png",
    }

    new_html = html
    for key, old_url in original_urls.items():
        new_url = new_images.get(key)
        if new_url and old_url in new_html:
            new_html = new_html.replace(old_url, new_url)
            logging.info(f"  [{key}] URL 교체: {old_url} -> {new_url}")
        elif new_url:
            logging.warning(f"  [{key}] 이전 URL {old_url} HTML에서 못 찾음")

    if new_html == html:
        # URL 교체 실패 → build_img_html로 전체 img 블록 재구성
        logging.warning("  URL 교체 실패 → img 블록 전체 재구성")
        captions = {
            "hero": "My Elderberry and Zinc testing routine.",
            "s1": "Testing Elderberry and Zinc during the first week.",
            "s2": "Tracking effects on immunity over time.",
            "s3": "Adjusting timing and dosage for best results.",
        }
        # 기존 img-container 블록 제거 후 sections에 재삽입
        # 간단하게: img src="" 교체
        for key, new_url in new_images.items():
            # old URL 패턴 찾기
            old_url = original_urls.get(key, "")
            if old_url:
                new_html = new_html.replace(old_url, new_url)

    logging.info(f"  HTML img 수: {len(re.findall('<img', new_html))}개")

    try:
        res = svc.posts().update(
            blogId=BLOG_ID, postId=POST_ID,
            body={"title": title, "content": new_html, "labels": labels},
            publish=False,
        ).execute()
        logging.info(f"\n예약 포스트 업데이트 완료")
        logging.info(f"  status: {res.get('status')}")
        logging.info(f"  scheduled: {res.get('published')}")
        logging.info(f"  url: {res.get('url')}")
    except Exception as e:
        logging.error(f"  포스트 업데이트 실패: {e}")


if __name__ == "__main__":
    run()
