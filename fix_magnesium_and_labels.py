"""
fix_magnesium_and_labels.py

1. Magnesium Complete Guide 포스트:
   - hero + s1 + s2 이미지 Imgur 업로드 후 HTML 주입
   - 제목을 검색 의도 기반으로 수정
   - 기존 labels 보존

2. B12, Citrulline, K2-2 포스트 labels 복원
"""

import re, pickle, base64, time, requests, logging, json
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
IMAGE_DIR  = BASE_DIR / "05_Images"
IMGUR_CID  = "546c25a59c58ad7"
LINKS_FILE = BASE_DIR / "20_Meta" / "published_links.json"

# ── Magnesium 포스트
MAG_POST_ID = "3723348937733675656"
MAG_TITLE   = "Magnesium Complete Guide: Benefits, Types, and Best Dosage"
MAG_IMAGES  = {
    "hero": IMAGE_DIR / "Magnesium_Complete_Guide_hero.png",
    "s1":   IMAGE_DIR / "Magnesium_Complete_Guide_s1.png",
    "s2":   IMAGE_DIR / "Magnesium_Complete_Guide_s2.png",
}
MAG_CAPTIONS = [
    "My Magnesium supplementation setup and testing notes.",
    "Tracking Magnesium effects on sleep and recovery.",
    "Adjusting my Magnesium form and timing for best results.",
]

# ── Label 복원 대상 (topic 기반으로 적절한 labels 지정)
LABEL_RESTORE = {
    "7123665939022173318": {
        "name": "Vitamin B12",
        "labels": ["VitaminB12", "Cobalamin", "NordicHealth", "NutriStackLab",
                   "BrainHealth", "Supplements", "Methylcobalamin", "EnergyMetabolism"],
    },
    "6521023620032722085": {
        "name": "Citrulline Malate",
        "labels": ["Citrulline", "CitrullineMalate", "PreWorkout", "NordicHealth",
                   "NutriStackLab", "Supplements", "Endurance", "NitricOxide"],
    },
    "7619540800960348092": {
        "name": "Vitamin K2 MK-7",
        "labels": ["VitaminK2", "MK7", "BoneHealth", "NordicHealth",
                   "NutriStackLab", "Supplements", "Cardiovascular", "K2Guide"],
    },
}


def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def upload_to_imgur(img_path: Path) -> str | None:
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
        else:
            logging.warning(f"  Imgur HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logging.warning(f"  Imgur error ({img_path.name}): {e}")
    return None


def build_img_html(url: str, alt: str, caption: str) -> str:
    return (
        f'<div style="margin:30px 0;text-align:center;">'
        f'<img src="{url}" alt="{alt}" '
        f'style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.1);"/>'
        f'<div style="margin-top:10px;font-size:0.9em;color:#666;font-style:italic;'
        f'padding:12px;text-align:center;">{caption}</div></div>'
    )


def build_hero_html(url: str) -> str:
    return (
        f'<div style="margin:20px 0 30px 0;text-align:center;">'
        f'<img src="{url}" alt="Magnesium supplement guide" '
        f'style="max-width:100%;height:auto;border-radius:12px;'
        f'box-shadow:0 6px 20px rgba(0,0,0,0.15);"/></div>'
    )


def inject_images_magnesium(html: str, hero_url: str, section_urls: list) -> str:
    """Hero는 첫 </p> 또는 </h1> 뒤에, 섹션 이미지는 H2 뒤에 균등 배치"""
    # 1. Hero image: 첫 번째 단락 또는 h2 앞에 삽입
    hero_block = "\n" + build_hero_html(hero_url) + "\n"

    # 첫 번째 </p> 위치 찾기
    first_p = re.search(r'</p>', html, re.IGNORECASE)
    if first_p:
        ins = first_p.end()
        html = html[:ins] + hero_block + html[ins:]
    else:
        # fallback: 맨 앞에 삽입
        html = hero_block + html

    # 2. Section images: H2 뒤에 균등 배치
    if not section_urls:
        return html

    h2_positions = [m.end() for m in re.finditer(r'</h2>', html, re.IGNORECASE)]
    if len(h2_positions) < 2:
        return html

    step = max(1, len(h2_positions) // (len(section_urls) + 1))
    insert_points = [h2_positions[min(i * step, len(h2_positions) - 1)]
                     for i in range(1, len(section_urls) + 1)]

    offset = 0
    for i, (pos, url) in enumerate(zip(insert_points, section_urls)):
        alt = "Magnesium supplement testing routine"
        cap = MAG_CAPTIONS[i % len(MAG_CAPTIONS)]
        block = "\n" + build_img_html(url, alt, cap) + "\n"
        actual = pos + offset
        html = html[:actual] + block + html[actual:]
        offset += len(block)

    return html


def fix_magnesium(svc):
    logging.info("=" * 55)
    logging.info(f"Magnesium fix (post_id={MAG_POST_ID})")

    # 1. 이미지 업로드
    uploaded = {}
    for key, path in MAG_IMAGES.items():
        if not path.exists():
            logging.warning(f"  Image not found: {path.name}")
            continue
        url = upload_to_imgur(path)
        if url:
            uploaded[key] = url
        time.sleep(1)

    if "hero" not in uploaded:
        logging.error("  Hero image upload failed — aborting")
        return

    logging.info(f"  Uploaded: {list(uploaded.keys())}")

    # 2. 현재 포스트 가져오기
    post   = svc.posts().get(blogId=BLOG_ID, postId=MAG_POST_ID).execute()
    html   = post.get("content", "")
    labels = post.get("labels", [])

    before = len(re.findall(r'<img', html, re.IGNORECASE))
    logging.info(f"  Images before: {before}")

    # 3. 이미지 주입
    section_urls = [uploaded[k] for k in ["s1", "s2"] if k in uploaded]
    new_html = inject_images_magnesium(html, uploaded["hero"], section_urls)

    after = len(re.findall(r'<img', new_html, re.IGNORECASE))
    logging.info(f"  Images after: {after}")

    # 4. Blogger 업데이트 (labels 보존)
    try:
        body = {"title": MAG_TITLE, "content": new_html}
        if labels:
            body["labels"] = labels
        res = svc.posts().update(blogId=BLOG_ID, postId=MAG_POST_ID, body=body).execute()
        logging.info(f"  Update OK: {res.get('url','')}")
        logging.info(f"  New title: {MAG_TITLE}")
        logging.info(f"  Labels preserved: {labels}")
    except Exception as e:
        logging.error(f"  Update FAILED: {e}")
        return

    # 5. published_links.json 업데이트
    items = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
    found = False
    for item in items:
        if item.get("post_id") == MAG_POST_ID:
            item["title"] = MAG_TITLE
            item["labels"] = labels
            found = True
            break
    if not found:
        # 포스트가 DB에 없으면 추가
        items.append({
            "post_id": MAG_POST_ID,
            "title": MAG_TITLE,
            "topic": "Magnesium Complete Guide",
            "labels": labels,
            "url": res.get("url", ""),
            "date": post.get("published", ""),
        })
        logging.info("  Added to published_links.json (was missing)")

    LINKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("  published_links.json updated")


def restore_labels(svc):
    logging.info("\n" + "=" * 55)
    logging.info("Labels restoration")

    items = json.loads(LINKS_FILE.read_text(encoding="utf-8"))

    for post_id, cfg in LABEL_RESTORE.items():
        name   = cfg["name"]
        labels = cfg["labels"]
        logging.info(f"\n  {name} [{post_id}]")

        try:
            post    = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
            title   = post.get("title", "")
            content = post.get("content", "")

            res = svc.posts().update(
                blogId=BLOG_ID, postId=post_id,
                body={"title": title, "content": content, "labels": labels}
            ).execute()
            logging.info(f"    Labels restored: {labels}")
            logging.info(f"    URL: {res.get('url','')}")

            # published_links.json 동기화
            for item in items:
                if item.get("post_id") == post_id:
                    item["labels"] = labels
                    break

        except Exception as e:
            logging.error(f"    FAILED: {e}")

        time.sleep(2)

    LINKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("\n  published_links.json saved")


def run():
    svc = get_service()
    fix_magnesium(svc)
    restore_labels(svc)
    logging.info("\nDone.")


if __name__ == "__main__":
    run()
