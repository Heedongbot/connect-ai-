"""
NutriStack Lab — Label Updater v1.0
전체 포스팅 라벨 자동 일괄 추가
"""

import json
import re
import time
import pickle
import logging
from pathlib import Path
from datetime import datetime

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('label_updater.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR            = Path(__file__).parent
TOKEN_FILE          = BASE_DIR / "token.pickle"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
SCOPES              = ['https://www.googleapis.com/auth/blogger']
BLOG_ID             = "2812259517039331714"
DELAY               = 2  # API Rate Limit 방지

# ============================================================
# 라벨 매칭 DB
# ============================================================
LABEL_RULES = [
    # 영양소별 규칙 (키워드 → 라벨 목록)
    # FUNDAMENTAL
    (["magnesium"],          ["Magnesium", "NordicHealth", "FUNDAMENTAL", "Minerals", "NutriStackLab"]),
    (["vitamin d3","vitamin d", "d3+k2", "d3 k2"], ["VitaminD3", "NordicHealth", "FUNDAMENTAL", "Immunity", "NutriStackLab"]),
    (["vitamin k2","k2"],    ["VitaminK2", "NordicHealth", "FUNDAMENTAL", "BoneHealth", "NutriStackLab"]),
    (["omega-3","omega 3","omega3","epa","dha","fish oil"], ["Omega3", "DHA", "EPA", "BrainHealth", "NordicHealth", "NutriStackLab"]),
    (["zinc"],               ["Zinc", "Immunity", "NordicHealth", "FUNDAMENTAL", "NutriStackLab"]),
    (["boron"],              ["Boron", "Testosterone", "SHBG", "NordicHealth", "NutriStackLab"]),
    (["vitamin c"],          ["VitaminC", "Immunity", "Antioxidant", "NordicHealth", "NutriStackLab"]),
    (["selenium"],           ["Selenium", "Antioxidant", "Thyroid", "NutriStackLab"]),
    (["iodine"],             ["Iodine", "Thyroid", "NordicHealth", "NutriStackLab"]),

    # COGNITIVE
    (["alpha-gpc","alpha gpc","alphagpc"], ["AlphaGPC", "Choline", "Nootropics", "BrainHealth", "NutriStackLab"]),
    (["cdp choline","cdp-choline","citicoline"], ["CDPCholine", "Choline", "Nootropics", "Memory", "NutriStackLab"]),
    (["choline"],            ["Choline", "Nootropics", "BrainHealth", "Memory", "NutriStackLab"]),
    (["l-theanine","theanine"], ["LTheanine", "Focus", "AlphaWaves", "Calm", "NutriStackLab"]),
    (["creatine"],           ["Creatine", "BrainEnergy", "Nootropics", "ATP", "NutriStackLab"]),
    (["lion's mane","lion mane","lionsmane"], ["LionsMane", "NGF", "Neuroplasticity", "BrainHealth", "NutriStackLab"]),
    (["bacopa"],             ["Bacopa", "Memory", "Adaptogen", "Nootropics", "NutriStackLab"]),
    (["phosphatidylserine","ps "],  ["PhosphatidylSerine", "BrainHealth", "Cortisol", "Memory", "NutriStackLab"]),
    (["rhodiola"],           ["Rhodiola", "Adaptogen", "Fatigue", "Stress", "NutriStackLab"]),
    (["ashwagandha"],        ["Ashwagandha", "Adaptogen", "Cortisol", "Stress", "NutriStackLab"]),
    (["ginkgo"],             ["Ginkgo", "Circulation", "Memory", "Nootropics", "NutriStackLab"]),
    (["magnesium l-threonate","magnesium threonate"], ["MagnesiumThreonate", "BrainHealth", "Memory", "Nootropics", "NutriStackLab"]),
    (["caffeine"],           ["Caffeine", "Focus", "Energy", "LTheanine", "NutriStackLab"]),
    (["5-htp"],              ["5HTP", "Serotonin", "Sleep", "Mood", "NutriStackLab"]),
    (["gaba"],               ["GABA", "Sleep", "Anxiety", "Calm", "NutriStackLab"]),

    # METABOLIC
    (["nmn"],                ["NMN", "NAD", "Longevity", "Aging", "NutriStackLab"]),
    (["nad+","nad "],        ["NAD", "NMN", "Longevity", "Mitochondria", "NutriStackLab"]),
    (["coq10","ubiquinol"],  ["CoQ10", "Mitochondria", "Energy", "Heart", "NutriStackLab"]),
    (["pqq"],                ["PQQ", "Mitochondria", "BDNF", "Cognitive", "NutriStackLab"]),
    (["berberine"],          ["Berberine", "AMPK", "Glucose", "Metabolic", "NutriStackLab"]),
    (["alpha lipoic","ala"], ["AlphaLipoicAcid", "Antioxidant", "Metabolic", "NutriStackLab"]),
    (["resveratrol"],        ["Resveratrol", "Longevity", "Antioxidant", "NutriStackLab"]),
    (["quercetin"],          ["Quercetin", "Immunity", "Antiviral", "Antioxidant", "NutriStackLab"]),

    # STRUCTURAL
    (["collagen"],           ["Collagen", "Joints", "Skin", "STRUCTURAL", "NutriStackLab"]),
    (["glucosamine"],        ["Glucosamine", "Joints", "Cartilage", "STRUCTURAL", "NutriStackLab"]),
    (["msm"],                ["MSM", "Sulfur", "Joints", "Connective", "NutriStackLab"]),
    (["hyaluronic"],         ["HyaluronicAcid", "Joints", "Skin", "STRUCTURAL", "NutriStackLab"]),
    (["silica","silicon"],   ["Silica", "BoneHealth", "Hair", "STRUCTURAL", "NutriStackLab"]),
    (["biotin"],             ["Biotin", "Hair", "Skin", "Metabolism", "NutriStackLab"]),

    # IMMUNE / GUT
    (["probiotics","probiotic"], ["Probiotics", "GutHealth", "Immunity", "Microbiome", "NutriStackLab"]),
    (["prebiotics","prebiotic"], ["Prebiotics", "GutHealth", "Microbiome", "NutriStackLab"]),
    (["glutathione"],        ["Glutathione", "Antioxidant", "Detox", "Immunity", "NutriStackLab"]),
    (["nac","n-acetyl"],     ["NAC", "Glutathione", "Antioxidant", "Detox", "NutriStackLab"]),
    (["elderberry"],         ["Elderberry", "Antiviral", "Immunity", "WinterHealth", "NutriStackLab"]),
    (["beta-glucan","beta glucan"], ["BetaGlucan", "Immunity", "GutHealth", "NutriStackLab"]),

    # 테마별
    (["nordic","mørketid","morketid","dark season"], ["NordicHealth", "Morkketid", "SeasonalHealth", "NutriStackLab"]),
    (["immune","immunity"],  ["Immunity", "ImmuneSupport", "NordicHealth", "NutriStackLab"]),
    (["brain","cognitive","cognition","nootropic"], ["BrainHealth", "Cognitive", "Nootropics", "NutriStackLab"]),
    (["sleep","melatonin"],  ["Sleep", "CircadianRhythm", "NordicHealth", "NutriStackLab"]),
    (["testosterone","hormone"], ["Testosterone", "Hormones", "NordicHealth", "NutriStackLab"]),
    (["inflammation","anti-inflammatory"], ["Inflammation", "Immunity", "NordicHealth", "NutriStackLab"]),
    (["longevity","aging","anti-aging"], ["Longevity", "AntiAging", "Mitochondria", "NutriStackLab"]),
    (["synergy","stack","protocol"], ["Synergy", "Stack", "NordicHealth", "NutriStackLab"]),
]

# 기본 라벨 (모든 포스팅 공통)
DEFAULT_LABELS = ["NordicHealth", "NutriStackLab", "Supplements"]


# ============================================================
# [1] 유틸리티
# ============================================================
def get_service():
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
    return build('blogger', 'v3', credentials=creds)


def get_all_posts(service):
    posts = []
    page_token = None
    while True:
        try:
            kwargs = {"blogId": BLOG_ID, "maxResults": 20, "status": "LIVE"}
            if page_token:
                kwargs["pageToken"] = page_token
            res = service.posts().list(**kwargs).execute()
            posts.extend(res.get('items', []))
            page_token = res.get('nextPageToken')
            if not page_token:
                break
            time.sleep(1)
        except Exception as e:
            logging.error(f"조회 오류: {e}")
            break
    return posts


def detect_labels(title, content=""):
    """제목과 내용에서 라벨 자동 감지"""
    text = (title + " " + content[:500]).lower()
    matched_labels = set(DEFAULT_LABELS)

    for keywords, labels in LABEL_RULES:
        for kw in keywords:
            if kw in text:
                matched_labels.update(labels)
                break

    # 중복 제거 + 최대 10개
    final = list(matched_labels)[:10]
    return final


# ============================================================
# [2] 라벨 업데이트
# ============================================================
def update_labels(service, post_id, title, labels):
    try:
        body = {"title": title, "labels": labels}
        res = service.posts().patch(
            blogId=BLOG_ID,
            postId=post_id,
            body=body
        ).execute()
        return True
    except Exception as e:
        logging.error(f"  라벨 업데이트 오류: {e}")
        return False


# ============================================================
# [3] 메인 실행
# ============================================================
def run_label_updater(force=False):
    """
    전체 포스팅 라벨 일괄 업데이트
    force=True: 기존 라벨 있어도 덮어쓰기
    force=False: 라벨 없는 포스팅만 처리
    """
    logging.info("🏷️ NutriStack Label Updater v1.0 시작")
    service = get_service()

    logging.info("📋 포스팅 목록 조회 중...")
    posts = get_all_posts(service)
    logging.info(f"  총 {len(posts)}개 포스팅 발견")

    success = 0
    skipped = 0
    failed = 0

    for i, post in enumerate(posts, 1):
        post_id   = post.get('id', '')
        title     = post.get('title', '')
        content   = post.get('content', '')
        cur_labels = post.get('labels', [])

        # 라벨 이미 있으면 스킵 (force 모드 아닐 때)
        if cur_labels and not force:
            logging.info(f"  ⏭️ [{i}/{len(posts)}] 스킵 (라벨 있음): {title[:45]}")
            skipped += 1
            continue

        # 라벨 자동 감지
        new_labels = detect_labels(title, content)

        logging.info(f"  🏷️ [{i}/{len(posts)}] {title[:45]}")
        logging.info(f"     라벨: {new_labels}")

        # 업데이트
        ok = update_labels(service, post_id, title, new_labels)
        if ok:
            success += 1
        else:
            failed += 1

        time.sleep(DELAY)

    logging.info(f"\n{'='*50}")
    logging.info(f"🏆 라벨 업데이트 완료!")
    logging.info(f"  ✅ 성공: {success}개")
    logging.info(f"  ⏭️ 스킵: {skipped}개")
    logging.info(f"  ❌ 실패: {failed}개")


def scan_labels():
    """라벨 현황 스캔 (수정 없이)"""
    logging.info("🔍 라벨 현황 스캔")
    service = get_service()
    posts = get_all_posts(service)

    no_label = []
    has_label = []

    for post in posts:
        title = post.get('title', '')
        labels = post.get('labels', [])
        if labels:
            has_label.append((title, labels))
        else:
            no_label.append(title)

    logging.info(f"\n📊 결과:")
    logging.info(f"  ✅ 라벨 있음: {len(has_label)}개")
    logging.info(f"  🔴 라벨 없음: {len(no_label)}개")

    if no_label:
        logging.info(f"\n🔴 라벨 없는 포스팅:")
        for t in no_label:
            labels = detect_labels(t)
            logging.info(f"  → {t[:50]}")
            logging.info(f"     예상 라벨: {labels}")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args:
        # 라벨 없는 것만 처리
        run_label_updater(force=False)

    elif args[0] == "all":
        # 전체 강제 업데이트
        logging.info("⚠️ 전체 강제 업데이트 모드")
        run_label_updater(force=True)

    elif args[0] == "scan":
        # 현황 스캔만
        scan_labels()

    else:
        print("""
사용법:
  python label_updater.py          # 라벨 없는 포스팅만 처리
  python label_updater.py all      # 전체 강제 업데이트
  python label_updater.py scan     # 현황 스캔만 (수정 없음)
        """)
