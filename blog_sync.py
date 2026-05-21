"""
NutriStack Lab — Blog Sync v1.0
기존 블로그 포스팅 → 옵시디언 학습 + 중복 방지 DB 완성

기능:
1. Blogger API로 전체 포스팅 조회
2. 각 포스팅 → 옵시디언 .md 파일 생성 (쌍방향 링크)
3. published_links.json 업데이트 (중복 방지)
4. 카테고리별 인덱스 파일 생성
5. 영양소별 관계 맵 생성
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
        logging.FileHandler('blog_sync.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR            = Path(__file__).parent
TOKEN_FILE          = BASE_DIR / "token.pickle"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
SCOPES              = ['https://www.googleapis.com/auth/blogger']
BLOG_ID             = "2812259517039331714"
BLOG_URL            = "https://www.nutristacklab.com"

# 옵시디언 경로
WIKI_DIR      = BASE_DIR / "10_Wiki"
DECISIONS_DIR = WIKI_DIR / "Decisions"
INDEX_DIR     = WIKI_DIR / "Index"
MAP_DIR       = WIKI_DIR / "Maps"
META_DIR      = BASE_DIR / "20_Meta"
LINKS_DB      = META_DIR / "published_links.json"
USED_TOPICS   = META_DIR / "used_topics.json"

for d in [DECISIONS_DIR, INDEX_DIR, MAP_DIR, META_DIR]:
    d.mkdir(exist_ok=True, parents=True)

# ============================================================
# 영양소 관계 DB
# ============================================================
NUTRIENT_RELATIONS = {
    "magnesium":   ["vitamin d","zinc","l-theanine","omega","calcium","k2"],
    "vitamin d":   ["magnesium","vitamin k","k2","omega","calcium","boron"],
    "vitamin d3":  ["magnesium","vitamin k","k2","omega","calcium","boron"],
    "omega":       ["vitamin d","magnesium","epa","dha","brain","inflammation"],
    "zinc":        ["quercetin","vitamin c","immune","magnesium","testosterone"],
    "l-theanine":  ["caffeine","creatine","magnesium","sleep","focus"],
    "creatine":    ["alpha-gpc","l-theanine","brain","atp","cognitive"],
    "alpha-gpc":   ["creatine","choline","cdp","brain","acetylcholine"],
    "lion":        ["bacopa","ngf","brain","neuroplasticity","cognitive"],
    "bacopa":      ["lion","ashwagandha","memory","stress","cognitive"],
    "collagen":    ["vitamin c","glucosamine","msm","joint","skin"],
    "quercetin":   ["zinc","vitamin c","immune","inflammation","antiviral"],
    "vitamin c":   ["quercetin","glutathione","collagen","immune","antioxidant"],
    "nmn":         ["resveratrol","nad","coq10","aging","longevity"],
    "coq10":       ["pqq","nmn","nad","mitochondria","energy"],
    "pqq":         ["coq10","nmn","mitochondria","bdnf","cognitive"],
    "berberine":   ["alpha lipoic","insulin","glucose","metabolic","ampk"],
    "ashwagandha": ["rhodiola","magnesium","cortisol","stress","adaptogen"],
    "boron":       ["vitamin d","testosterone","magnesium","shbg","bone"],
    "glutathione": ["vitamin c","nac","selenium","antioxidant","detox"],
    "probiotics":  ["prebiotics","gut","brain","immune","microbiome"],
    "glucosamine": ["msm","collagen","joint","chondroitin","cartilage"],
    "msm":         ["glucosamine","collagen","vitamin c","sulfur","joint"],
}

CATEGORY_MAP = {
    "COGNITIVE":   ["cognitive","brain","memory","focus","nootropic",
                    "lion","bacopa","creatine","choline","theanine","alpha-gpc"],
    "FUNDAMENTAL": ["vitamin d","magnesium","zinc","omega","k2","boron","calcium"],
    "METABOLIC":   ["nmn","coq10","pqq","berberine","nad","mitochondria","resveratrol"],
    "STRUCTURAL":  ["collagen","glucosamine","msm","joint","bone","skin","silica"],
    "IMMUNE":      ["probiotic","immune","quercetin","vitamin c","glutathione","elderberry"],
}

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
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)
    return build('blogger', 'v3', credentials=creds)


def get_all_posts(service):
    posts, page_token = [], None
    while True:
        kwargs = {"blogId": BLOG_ID, "maxResults": 20, "status": "LIVE"}
        if page_token:
            kwargs["pageToken"] = page_token
        res = service.posts().list(**kwargs).execute()
        posts.extend(res.get('items', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break
        time.sleep(0.5)
    return posts


def detect_category(title):
    t = title.lower()
    for cat, keywords in CATEGORY_MAP.items():
        if any(k in t for k in keywords):
            return cat
    return "GENERAL"


def extract_nutrients(title):
    t = title.lower()
    found = []
    for kw in NUTRIENT_RELATIONS.keys():
        if kw in t:
            found.append(kw)
    return found[:5]


def count_words(html):
    return len(re.sub(r'<[^>]+>', ' ', html).split())


def get_related_posts(nutrients, all_posts_data, current_url):
    """영양소 기반 관련 포스팅 찾기"""
    related = []
    for post in all_posts_data:
        if post["url"] == current_url:
            continue
        post_nutrients = post.get("nutrients", [])
        # 공통 영양소
        common = set(nutrients) & set(post_nutrients)
        # 연관 영양소 체크
        related_count = 0
        for n in nutrients:
            for rel in NUTRIENT_RELATIONS.get(n, []):
                if any(rel in pn for pn in post_nutrients):
                    related_count += 1
        if common or related_count > 0:
            score = len(common) * 3 + related_count
            related.append((score, post))

    related.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in related[:5]]


# ============================================================
# [2] 옵시디언 파일 생성
# ============================================================
def create_obsidian_note(post_data, related_posts, all_posts_data):
    """포스팅 → 옵시디언 .md 파일"""
    title    = post_data["title"]
    url      = post_data["url"]
    date     = post_data["date"]
    category = post_data["category"]
    nutrients= post_data["nutrients"]
    words    = post_data["word_count"]
    labels   = post_data.get("labels", [])

    # 쌍방향 링크 생성
    nutrient_links = " | ".join([
        f"[[{n.title().replace('-',' ')}]]"
        for n in nutrients
    ]) if nutrients else "없음"

    # 연관 영양소 링크
    all_related_nutrients = set()
    for n in nutrients:
        for rel in NUTRIENT_RELATIONS.get(n, []):
            all_related_nutrients.add(rel)
    related_nutrient_links = " | ".join([
        f"[[{n.title().replace('-',' ')}]]"
        for n in list(all_related_nutrients)[:8]
    ]) if all_related_nutrients else "없음"

    # 관련 포스팅 링크
    related_links_md = ""
    for rp in related_posts[:5]:
        rp_title = rp["title"]
        related_links_md += f"- [[{rp_title}]]\n"
    if not related_links_md:
        related_links_md = "- 관련 포스팅 없음\n"

    # 카테고리별 다음 주제 제안
    suggestions = []
    for kw in nutrients[:2]:
        for rel in NUTRIENT_RELATIONS.get(kw, [])[:3]:
            suggestion = f"{kw.title()} and {rel.title()}"
            # 이미 발행된 조합인지 확인
            is_published = any(
                rel.lower() in p["title"].lower()
                for p in all_posts_data
            )
            if not is_published:
                suggestions.append(suggestion)

    suggestion_md = "\n".join([
        f"- [ ] {s}" for s in suggestions[:3]
    ]) if suggestions else "- 모든 조합 발행 완료"

    # 마크다운 작성
    md = f"""---
title: {title}
url: {url}
date: {date}
category: {category}
nutrients: {', '.join(nutrients)}
word_count: {words}
labels: {', '.join(labels)}
status: published
---

# {title}

## 📊 포스팅 정보
| 항목 | 내용 |
|------|------|
| **발행일** | {date} |
| **카테고리** | {category} |
| **단어수** | {words:,}개 |
| **URL** | [링크]({url}) |

## 🔗 핵심 영양소 (쌍방향 링크)
{nutrient_links}

## 🔗 연관 영양소
{related_nutrient_links}

## 📚 관련 포스팅
{related_links_md}

## 💡 다음 추천 주제 (미발행 조합)
{suggestion_md}

## 🏷️ 라벨
{', '.join([f'`{l}`' for l in labels]) if labels else '없음'}

---
*NutriStack Blog Sync v1.0 | {datetime.now().strftime('%Y-%m-%d')}*
"""

    # 파일명 (특수문자 제거)
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
    fp = DECISIONS_DIR / f"{safe_title}.md"
    fp.write_text(md, encoding='utf-8')
    return fp.name


# ============================================================
# [3] 카테고리별 인덱스 생성
# ============================================================
def create_category_index(all_posts_data):
    """카테고리별 인덱스 파일 생성"""
    categories = {}
    for post in all_posts_data:
        cat = post["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(post)

    for cat, posts in categories.items():
        posts.sort(key=lambda x: x["date"], reverse=True)
        md = f"# {cat} 카테고리 인덱스\n\n"
        md += f"총 {len(posts)}개 포스팅\n\n"
        md += "## 포스팅 목록\n"
        for post in posts:
            md += (f"- [[{post['title'][:50]}]] "
                   f"({post['date']}) "
                   f"{post['word_count']:,}단어\n")

        fp = INDEX_DIR / f"{cat}_Index.md"
        fp.write_text(md, encoding='utf-8')
        logging.info(f"  📁 {cat} 인덱스: {len(posts)}개")


# ============================================================
# [4] 영양소 관계 맵 생성
# ============================================================
def create_nutrient_map(all_posts_data):
    """영양소별 발행 현황 맵"""
    nutrient_posts = {}
    for post in all_posts_data:
        for n in post.get("nutrients", []):
            if n not in nutrient_posts:
                nutrient_posts[n] = []
            nutrient_posts[n].append(post)

    md = "# NutriStack 영양소 관계 맵\n\n"
    md += f"총 {len(all_posts_data)}개 포스팅 | {len(nutrient_posts)}종 영양소\n\n"

    for nutrient, posts in sorted(nutrient_posts.items()):
        md += f"\n## [[{nutrient.title().replace('-',' ')}]] ({len(posts)}개 포스팅)\n"
        # 연관 영양소
        related = NUTRIENT_RELATIONS.get(nutrient, [])
        if related:
            md += "**연관**: " + " | ".join([
                f"[[{r.title().replace('-',' ')}]]" for r in related[:5]
            ]) + "\n"
        # 발행된 포스팅
        for post in posts[:3]:
            md += f"- [[{post['title'][:50]}]]\n"
        if len(posts) > 3:
            md += f"- ...외 {len(posts)-3}개\n"

    fp = MAP_DIR / "Nutrient_Relation_Map.md"
    fp.write_text(md, encoding='utf-8')
    logging.info(f"  🗺️ 영양소 관계 맵 생성: {len(nutrient_posts)}종")


# ============================================================
# [5] 메인 동기화
# ============================================================
def run_sync(force=False):
    """전체 블로그 → 옵시디언 동기화"""
    logging.info("🔄 NutriStack Blog Sync v1.0 시작")
    logging.info(f"  블로그: {BLOG_URL}")

    # Blogger 조회
    service = get_service()
    logging.info("📋 포스팅 목록 조회 중...")
    posts = get_all_posts(service)
    logging.info(f"  총 {len(posts)}개 포스팅 발견")

    # 기존 DB 로드
    existing_db = []
    if LINKS_DB.exists() and not force:
        try:
            existing_db = json.loads(LINKS_DB.read_text(encoding='utf-8'))
        except:
            pass
    existing_urls = {e.get("url","") for e in existing_db}

    # 포스팅 데이터 처리
    all_posts_data = []
    new_count = 0

    for i, post in enumerate(posts, 1):
        title   = post.get('title','')
        url     = post.get('url','')
        content = post.get('content','')
        labels  = post.get('labels', [])
        published = post.get('published','')[:10]

        # 데이터 추출
        category = detect_category(title)
        nutrients = extract_nutrients(title)
        words = count_words(content)

        post_data = {
            "title":      title,
            "url":        url,
            "date":       published,
            "category":   category,
            "nutrients":  nutrients,
            "word_count": words,
            "labels":     labels,
            "topic":      title,
        }
        all_posts_data.append(post_data)

        if url not in existing_urls:
            new_count += 1

        logging.info(f"  [{i}/{len(posts)}] {title[:50]}")
        logging.info(f"    카테고리: {category} | 영양소: {nutrients} | {words}단어")

    # 옵시디언 노트 생성
    logging.info(f"\n📝 옵시디언 노트 생성 중...")
    for i, post_data in enumerate(all_posts_data, 1):
        related = get_related_posts(
            post_data["nutrients"], all_posts_data, post_data["url"]
        )
        fname = create_obsidian_note(post_data, related, all_posts_data)
        logging.info(f"  [{i}/{len(all_posts_data)}] ✅ {fname[:50]}")

    # 카테고리 인덱스 생성
    logging.info(f"\n📁 카테고리 인덱스 생성...")
    create_category_index(all_posts_data)

    # 영양소 관계 맵 생성
    logging.info(f"\n🗺️ 영양소 관계 맵 생성...")
    create_nutrient_map(all_posts_data)

    # published_links.json 업데이트 (중복 방지 DB)
    logging.info(f"\n💾 published_links.json 업데이트...")
    LINKS_DB.parent.mkdir(exist_ok=True, parents=True)
    LINKS_DB.write_text(
        json.dumps(all_posts_data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    logging.info(f"  ✅ {len(all_posts_data)}개 포스팅 저장")

    # used_topics.json 업데이트
    used_topics = [p["title"] for p in all_posts_data]
    USED_TOPICS.write_text(
        json.dumps(used_topics, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    logging.info(f"  ✅ used_topics.json: {len(used_topics)}개 주제")

    # 최종 보고
    logging.info(f"\n{'='*50}")
    logging.info(f"🏆 Blog Sync 완료!")
    logging.info(f"  📝 총 포스팅: {len(all_posts_data)}개")
    logging.info(f"  🆕 신규 포스팅: {new_count}개")
    logging.info(f"  📚 옵시디언 노트: {len(all_posts_data)}개")
    logging.info(f"  📁 카테고리 인덱스: 5개")
    logging.info(f"  🗺️ 영양소 관계 맵: 1개")
    logging.info(f"\n  📂 저장 위치:")
    logging.info(f"     노트:  {DECISIONS_DIR}")
    logging.info(f"     인덱스: {INDEX_DIR}")
    logging.info(f"     맵:    {MAP_DIR}")
    logging.info(f"     DB:    {LINKS_DB}")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args:
        run_sync()

    elif args[0] == "force":
        logging.info("⚡ 강제 재동기화")
        run_sync(force=True)

    elif args[0] == "stats":
        # 통계만 출력
        if LINKS_DB.exists():
            db = json.loads(LINKS_DB.read_text(encoding='utf-8'))
            logging.info(f"\n📊 Blog Sync 현황:")
            logging.info(f"  총 포스팅: {len(db)}개")
            cats = {}
            for p in db:
                c = p.get("category","")
                cats[c] = cats.get(c,0) + 1
            for cat, cnt in sorted(cats.items()):
                logging.info(f"  {cat}: {cnt}개")
        else:
            logging.info("❌ DB 없음. python blog_sync.py 먼저 실행하세요.")

    else:
        print("""
사용법:
  python blog_sync.py          # 전체 동기화
  python blog_sync.py force    # 강제 재동기화
  python blog_sync.py stats    # 통계만 출력
        """)
