"""
NutriStack Lab — Pinterest Auto Poster v1.0
블로그 포스팅 발행 시 Pinterest 자동 핀 생성
"""

import json
import re
import time
import logging
import requests
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('pinterest.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR       = Path(__file__).parent
CONFIG_FILE    = BASE_DIR / "pinterest_config.json"
POSTED_FILE    = BASE_DIR / "20_Meta" / "pinterest_posted.json"
PINTEREST_API  = "https://api.pinterest.com/v5"

# ============================================================
# 보드 매핑 (카테고리 → 보드 이름)
# ============================================================
BOARD_MAP = {
    "COGNITIVE":   "Nordic Brain Health & Nootropics",
    "FUNDAMENTAL": "Nordic Supplement Protocols",
    "METABOLIC":   "Longevity & Metabolic Health",
    "STRUCTURAL":  "Joint & Structural Health",
    "IMMUNE":      "Nordic Immune Defense",
    "GENERAL":     "NutriStack Lab Blog",
}

# 카테고리 감지 키워드
CATEGORY_KEYWORDS = {
    "COGNITIVE":   ["brain","cognitive","memory","focus","nootropic",
                    "lion","bacopa","creatine","choline","theanine",
                    "phosphatidylserine","rhodiola","ashwagandha","nmn"],
    "FUNDAMENTAL": ["vitamin d","magnesium","zinc","omega","k2",
                    "boron","calcium","vitamin c","iodine","selenium"],
    "METABOLIC":   ["coq10","pqq","berberine","nad","mitochondria",
                    "resveratrol","quercetin","alpha lipoic"],
    "STRUCTURAL":  ["collagen","glucosamine","msm","joint","bone",
                    "hyaluronic","silica","biotin"],
    "IMMUNE":      ["probiotic","immune","immunity","elderberry",
                    "glutathione","quercetin","vitamin c","zinc"],
}

# ============================================================
# [1] 유틸리티
# ============================================================
def load_config():
    if not CONFIG_FILE.exists():
        logging.error("❌ pinterest_config.json 없음!")
        return None
    return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))

def load_posted():
    if POSTED_FILE.exists():
        return json.loads(POSTED_FILE.read_text(encoding='utf-8'))
    return []

def save_posted(url, pin_id, title):
    data = load_posted()
    data.append({
        "url": url,
        "pin_id": pin_id,
        "title": title,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    POSTED_FILE.parent.mkdir(exist_ok=True, parents=True)
    POSTED_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
    )

def detect_category(title):
    t = title.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return category
    return "GENERAL"

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

# ============================================================
# [2] 보드 관리
# ============================================================
def get_or_create_board(token, board_name):
    """보드 ID 조회 — config 캐시 우선 사용"""
    # 1. config에 저장된 board_ids 먼저 확인
    config = load_config()
    if config:
        board_ids = config.get("board_ids", {})
        # 정확한 이름 매칭
        if board_name in board_ids:
            logging.info(f"  📌 캐시 보드 사용: {board_name}")
            return board_ids[board_name]
        # 부분 이름 매칭
        for name, bid in board_ids.items():
            if board_name.lower() in name.lower() or name.lower() in board_name.lower():
                logging.info(f"  📌 유사 보드 사용: {name}")
                return bid

    # 2. API로 보드 목록 조회
    headers = get_headers(token)
    try:
        r = requests.get(
            f"{PINTEREST_API}/boards",
            headers=headers,
            params={"page_size": 25},
            timeout=15
        )
        if r.status_code == 200:
            boards = r.json().get("items", [])
            for board in boards:
                if board.get("name","").lower() == board_name.lower():
                    logging.info(f"  📌 API 보드 사용: {board_name}")
                    return board.get("id")
    except Exception as e:
        logging.warning(f"  보드 조회 오류: {e}")

    logging.error(f"  ❌ 보드 없음: {board_name}")
    logging.error(f"     → python pinterest_poster.py boards 실행 후 다시 시도하세요!")
    return None

# ============================================================
# [3] 핀 생성
# ============================================================
def generate_pin_description(title, url):
    """핀 설명 자동 생성"""
    # 제목에서 핵심 키워드 추출
    keywords = []
    nutrient_hints = [
        "Magnesium", "Vitamin D3", "Omega-3", "L-Theanine", "Creatine",
        "Lion's Mane", "Bacopa", "CoQ10", "NMN", "Quercetin", "Collagen",
        "Probiotics", "Glutathione", "Boron", "Zinc", "Vitamin C"
    ]
    for n in nutrient_hints:
        if n.lower() in title.lower():
            keywords.append(n)

    # 설명 생성
    desc = (
        f"{title}\n\n"
        f"Discover the science-backed Nordic approach to optimal health. "
        f"NutriStack Lab delivers research-driven supplement protocols "
        f"for peak cognitive and physical performance.\n\n"
        f"🔬 Evidence-based • 🌿 Nordic-optimized • 📊 PubMed-cited\n\n"
        f"Read the full guide: {url}\n\n"
    )

    # 해시태그 추가
    hashtags = ["#NordicHealth", "#Supplements", "#NutriStackLab",
                "#HealthOptimization", "#Nootropics"]
    for kw in keywords[:3]:
        clean_kw = kw.replace(' ','').replace('-','').replace("'","")
        hashtags.append(f"#{clean_kw}")

    desc += " ".join(hashtags[:8])
    return desc[:500]  # Pinterest 500자 제한


def create_pin(token, board_id, title, url, image_url, description):
    """Pinterest 핀 생성"""
    headers = get_headers(token)

    # Drive URL을 직접 이미지로 변환
    # drive.google.com/thumbnail → 직접 이미지 URL
    if "drive.google.com" in image_url:
        # Drive thumbnail URL 그대로 사용
        media_source = {
            "source_type": "image_url",
            "url": image_url
        }
    else:
        media_source = {
            "source_type": "image_url",
            "url": image_url
        }

    payload = {
        "title": title[:100],  # Pinterest 100자 제한
        "description": description,
        "link": url,
        "board_id": board_id,
        "media_source": media_source
    }

    try:
        r = requests.post(
            f"{PINTEREST_API}/pins",
            headers=headers,
            json=payload,
            timeout=30
        )
        if r.status_code in [200, 201]:
            pin_id = r.json().get('id', '')
            pin_url = f"https://pinterest.com/pin/{pin_id}"
            logging.info(f"  ✅ 핀 생성 성공!")
            logging.info(f"     핀 URL: {pin_url}")
            return pin_id
        else:
            logging.error(f"  ❌ 핀 생성 실패: {r.status_code}")
            logging.error(f"     응답: {r.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"  ❌ 핀 생성 오류: {e}")
        return None


# ============================================================
# [4] 메인 — 포스팅 핀 생성
# ============================================================
def post_to_pinterest(title, url, image_url=None):
    """
    블로그 포스팅 → Pinterest 핀 자동 생성
    title: 포스팅 제목
    url: 포스팅 URL
    image_url: 이미지 URL (Drive URL)
    """
    logging.info(f"\n📌 Pinterest 핀 생성 시작")
    logging.info(f"   제목: {title[:50]}")
    logging.info(f"   URL: {url}")

    # 이미 포스팅된 URL 체크
    posted = load_posted()
    if any(p.get('url') == url for p in posted):
        logging.info(f"  ⏭️ 이미 핀 생성됨 — 스킵")
        return False

    # 설정 로드
    config = load_config()
    if not config:
        return False

    token = config.get('access_token', '')
    if not token:
        logging.error("  ❌ access_token 없음!")
        return False

    # 카테고리 감지 → 보드 선택
    category = detect_category(title)
    board_name = BOARD_MAP.get(category, BOARD_MAP["GENERAL"])
    logging.info(f"  📂 카테고리: {category} → 보드: {board_name}")

    # 보드 ID 가져오기 (없으면 생성)
    board_id = get_or_create_board(token, board_name)
    if not board_id:
        logging.error("  ❌ 보드 ID 획득 실패")
        return False

    # 이미지 URL 없으면 기본 이미지 사용
    if not image_url:
        image_url = "https://drive.google.com/thumbnail?id=1D7B95c8kHM2E9VKTlFylYxkBzZVNWR_B&sz=s1000"

    # 핀 설명 생성
    description = generate_pin_description(title, url)

    # 핀 생성
    pin_id = create_pin(token, board_id, title, url, image_url, description)

    if pin_id:
        save_posted(url, pin_id, title)
        logging.info(f"  ✅ Pinterest 자동 포스팅 완료!")
        return True
    return False


# ============================================================
# [5] 기존 포스팅 일괄 핀 생성
# ============================================================
def bulk_post_from_blogger():
    """
    Blogger 전체 포스팅 → Pinterest 일괄 핀 생성
    """
    import pickle
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    TOKEN_FILE          = BASE_DIR / "token.pickle"
    CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
    BLOG_ID             = "2812259517039331714"
    SCOPES              = ['https://www.googleapis.com/auth/blogger']

    # Blogger 서비스
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)

    service = build('blogger', 'v3', credentials=creds)

    # 전체 포스팅 조회
    posts = []
    page_token = None
    while True:
        kwargs = {"blogId": BLOG_ID, "maxResults": 20, "status": "LIVE"}
        if page_token:
            kwargs["pageToken"] = page_token
        res = service.posts().list(**kwargs).execute()
        posts.extend(res.get('items', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break
        time.sleep(1)

    logging.info(f"  총 {len(posts)}개 포스팅 발견")

    # 이미 포스팅된 목록 로드하여 필터링
    posted_data = load_posted()
    posted_urls = {p.get('url') for p in posted_data if p.get('url')}
    
    unposted_posts = [post for post in posts if post.get('url') not in posted_urls]
    skipped = len(posts) - len(unposted_posts)
    
    logging.info(f"  ⏭️ 이미 핀 생성된 포스팅 {skipped}개 제외")
    logging.info(f"  🚀 새로 업로드할 포스팅 {len(unposted_posts)}개 시작")

    success = 0
    failed = 0

    for i, post in enumerate(unposted_posts, 1):
        title   = post.get('title', '')
        url     = post.get('url', '')
        content = post.get('content', '')

        # 이미지 URL 추출 (Drive URL)
        img_urls = re.findall(
            r'https://drive\.google\.com/thumbnail\?[^"\']+', content
        )
        image_url = img_urls[0] if img_urls else None

        logging.info(f"\n[{i}/{len(unposted_posts)}] {title[:45]}")

        ok = post_to_pinterest(title, url, image_url)
        if ok:
            success += 1
        else:
            failed += 1

        # Rate limit 방지
        time.sleep(3)

    logging.info(f"\n{'='*50}")
    logging.info(f"🏆 Pinterest 일괄 포스팅 완료!")
    logging.info(f"  ✅ 성공: {success}개")
    if failed > 0:
        logging.info(f"  ❌ 실패: {failed}개")
    logging.info(f"  ⏭️ 기존 스킵: {skipped}개")


# ============================================================
# [6] 실행
# ============================================================
if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args:
        print("""
NutriStack Pinterest Auto Poster v1.0

사용법:
  python pinterest_poster.py test          # 연결 테스트
  python pinterest_poster.py bulk          # 전체 포스팅 일괄 핀 생성
  python pinterest_poster.py history       # 핀 생성 이력
  python pinterest_poster.py post [URL] [TITLE]  # 단일 포스팅
        """)

    elif args[0] == "test":
        # 연결 테스트
        config = load_config()
        if config:
            token = config.get('access_token', '')
            r = requests.get(
                f"{PINTEREST_API}/user_account",
                headers=get_headers(token),
                timeout=15
            )
            if r.status_code == 200:
                user = r.json()
                logging.info(f"✅ Pinterest 연결 성공!")
                logging.info(f"   계정: {user.get('username', '')}")
                logging.info(f"   이름: {user.get('business_name', user.get('username', ''))}")
            else:
                logging.error(f"❌ 연결 실패: {r.status_code} {r.text[:100]}")

    elif args[0] == "bulk":
        # 전체 포스팅 일괄 핀 생성
        logging.info("🚀 전체 포스팅 일괄 Pinterest 핀 생성 시작")
        bulk_post_from_blogger()

    elif args[0] == "history":
        # 핀 생성 이력
        posted = load_posted()
        logging.info(f"📋 Pinterest 핀 이력 ({len(posted)}개):")
        for p in posted[-20:]:
            logging.info(f"  {p['date']} — {p['title'][:45]}")

    elif args[0] == "post" and len(args) >= 3:
        url   = args[1]
        title = " ".join(args[2:])
        post_to_pinterest(title, url)

    elif args[0] == "boards":
        # 보드 목록 조회 + config에 자동 저장
        config = load_config()
        if config:
            token = config.get("access_token", "")
            r = requests.get(
                f"{PINTEREST_API}/boards",
                headers=get_headers(token),
                params={"page_size": 25},
                timeout=15
            )
            if r.status_code == 200:
                boards = r.json().get("items", [])
                logging.info(f"\n📋 보드 목록 ({len(boards)}개):")
                board_ids = {}
                for b in boards:
                    name = b.get("name","")
                    bid  = b.get("id","")
                    logging.info(f"  [{bid}] {name}")
                    board_ids[name] = bid
                # config에 저장
                config["board_ids"] = board_ids
                CONFIG_FILE.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                logging.info(f"\n✅ 보드 ID pinterest_config.json에 저장 완료!")
            else:
                logging.error(f"❌ 보드 조회 실패: {r.status_code} {r.text[:100]}")