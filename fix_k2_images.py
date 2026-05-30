"""
fix_k2_images.py — K2 포스트 섹션 이미지 주입

두 K2 포스트 (post_id: 1445361037999783114, 7619540800960348092) 에
섹션 이미지가 누락되어 있어 Imgur 업로드 후 HTML에 주입합니다.

사용 이미지:
  K2-1: Vitamin K2 _MK-7_ Complete Guide_s1~s3.png (기존 파일)
  K2-2: 동일 이미지 재업로드 (별도 Imgur URL)
"""

import re, pickle, base64, time, requests, logging
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

BASE_DIR    = Path(__file__).parent
TOKEN_FILE  = BASE_DIR / "token.pickle"
BLOG_ID     = "2812259517039331714"
IMAGE_DIR   = BASE_DIR / "05_Images"
IMGUR_CID   = "546c25a59c58ad7"

K2_POSTS = {
    "K2-1": {
        "post_id": "1445361037999783114",
        "img_files": [
            IMAGE_DIR / "Vitamin K2 _MK-7_ Complete Guide_s1.png",
            IMAGE_DIR / "Vitamin K2 _MK-7_ Complete Guide_s2.png",
            IMAGE_DIR / "Vitamin K2 _MK-7_ Complete Guide_s3.png",
        ],
        "topic": "Vitamin K2 MK-7",
    },
    "K2-2": {
        "post_id": "7619540800960348092",
        "img_files": [
            IMAGE_DIR / "Vitamin K2 _MK-7_ Complete Guide_s1.png",
            IMAGE_DIR / "Vitamin K2 _MK-7_ Complete Guide_s2.png",
            IMAGE_DIR / "Vitamin K2 _MK-7_ Complete Guide_s3.png",
        ],
        "topic": "Vitamin K2 MK-7",
    },
}

SECTION_CAPTIONS = [
    "My Vitamin K2 (MK-7) testing routine.",
    "Tracking Vitamin K2 effects over several weeks.",
    "Adjusting my K2 protocol based on results.",
]

# ── 유틸리티

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
            logging.info(f"  ✅ Imgur 업로드: {img_path.name} → {url}")
            return url
    except Exception as e:
        logging.warning(f"  Imgur 실패 ({img_path.name}): {e}")
    return None

def build_img_html(url: str, alt: str, caption: str) -> str:
    return (
        f'<div style="margin:30px 0;text-align:center;">'
        f'<img src="{url}" alt="{alt}" '
        f'style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.1);"/>'
        f'<div style="margin-top:10px;font-size:0.9em;color:#666;font-style:italic;'
        f'padding:12px;text-align:center;">{caption}</div></div>'
    )

def inject_images_after_h2(html: str, img_urls: list[str]) -> str:
    """H2 태그 이후마다 섹션 이미지를 균등하게 삽입"""
    h2_positions = [m.end() for m in re.finditer(r'</h2>', html, re.IGNORECASE)]
    if len(h2_positions) < 2 or not img_urls:
        return html

    # h2 개수 기준으로 균등 간격 선택
    step = max(1, len(h2_positions) // (len(img_urls) + 1))
    insert_points = [h2_positions[min(i * step, len(h2_positions)-1)] for i in range(1, len(img_urls)+1)]

    # 역순으로 삽입 (인덱스 밀림 방지)
    offset = 0
    for i, (pos, url) in enumerate(zip(insert_points, img_urls)):
        alt = "Vitamin K2 MK-7 supplement routine"
        cap = SECTION_CAPTIONS[i % len(SECTION_CAPTIONS)]
        img_block = "\n" + build_img_html(url, alt, cap) + "\n"
        actual_pos = pos + offset
        html = html[:actual_pos] + img_block + html[actual_pos:]
        offset += len(img_block)

    return html

# ── Blogger API

def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def run():
    svc = get_service()

    for label, cfg in K2_POSTS.items():
        post_id   = cfg["post_id"]
        img_files = cfg["img_files"]

        logging.info(f"\n{'='*55}\n{label} (post_id={post_id})")

        # 1. Imgur 업로드
        img_urls = []
        for f in img_files:
            if not f.exists():
                logging.warning(f"  ⚠️ 파일 없음: {f.name}")
                continue
            url = upload_to_imgur(f)
            if url:
                img_urls.append(url)
            time.sleep(1)

        if not img_urls:
            logging.error(f"  이미지 업로드 실패 — {label} 건너뜀")
            continue

        logging.info(f"  {len(img_urls)}개 이미지 업로드 완료")

        # 2. 현재 HTML 가져오기
        post    = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
        html    = post.get("content", "")
        title   = post.get("title", "")
        before_count = len(re.findall(r'<img', html, re.IGNORECASE))
        logging.info(f"  현재 이미지 수: {before_count}")

        # 3. 이미지 주입
        new_html = inject_images_after_h2(html, img_urls)
        after_count = len(re.findall(r'<img', new_html, re.IGNORECASE))
        logging.info(f"  주입 후 이미지 수: {after_count}")

        # 4. Blogger 업데이트 (labels 보존)
        try:
            existing_labels = post.get("labels", [])
            body = {"title": title, "content": new_html}
            if existing_labels:
                body["labels"] = existing_labels
            res = svc.posts().update(
                blogId=BLOG_ID, postId=post_id,
                body=body
            ).execute()
            logging.info(f"  ✅ 업데이트 완료: {res.get('url','')}")
        except Exception as e:
            logging.error(f"  Blogger 업데이트 실패: {e}")

        time.sleep(2)


if __name__ == "__main__":
    run()
