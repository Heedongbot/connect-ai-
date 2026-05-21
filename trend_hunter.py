"""
NutriStack Lab — Trend Hunter v1.0
Google Trends + Reddit 실시간 트렌드 수집 → 주제 자동 선정
"""
import json
import time
import logging
import requests
import re
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('trend_hunter.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR       = Path(__file__).parent
META_DIR       = BASE_DIR / "20_Meta"
TOPIC_BANK     = META_DIR / "topic_bank.json"
USED_TOPICS    = META_DIR / "used_topics.json"
CONFIG_FILE    = BASE_DIR / "config.json"

META_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 장건강 + 음식 조합 핵심 키워드
# ============================================================
SEED_KEYWORDS = [
    "gut health", "probiotics", "prebiotics", "digestive health",
    "leaky gut", "gut microbiome", "digestive enzymes", "fiber supplement",
    "fermented foods", "gut healing", "bloating", "IBS supplement",
    "gut brain axis", "postbiotics", "butyrate", "L-glutamine gut",
    "magnesium digestion", "zinc gut health", "omega-3 gut",
    "vitamin D gut", "collagen gut", "aloe vera gut",
]

FOOD_KEYWORDS = [
    "foods for gut health", "best foods probiotics", "fiber rich foods",
    "fermented foods list", "gut healing diet", "foods that help digestion",
    "prebiotic foods", "foods for leaky gut", "anti inflammatory foods gut",
    "foods to avoid gut", "yogurt gut health", "kefir benefits",
    "sauerkraut gut", "kimchi gut health", "bone broth gut",
]

# ============================================================
# Discord 보고
# ============================================================
def report_to_discord(message):
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        webhook_url = cfg.get("webhook_url", "")
        if webhook_url:
            requests.post(webhook_url, json={"content": f"🌿 **[NutriStack Lab]** {message}"}, timeout=5)
    except:
        pass

# ============================================================
# 사용된 주제 로드
# ============================================================
def load_used_topics():
    if USED_TOPICS.exists():
        try:
            data = json.loads(USED_TOPICS.read_text(encoding='utf-8'))
            return [u.get("topic", "") if isinstance(u, dict) else u for u in data]
        except:
            return []
    return []

def save_used_topic(topic):
    used = []
    if USED_TOPICS.exists():
        try:
            used = json.loads(USED_TOPICS.read_text(encoding='utf-8'))
        except:
            pass
    used.append({"topic": topic, "date": datetime.now().strftime("%Y-%m-%d")})
    USED_TOPICS.write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding='utf-8')

# ============================================================
# 주제 은행 로드/저장
# ============================================================
def load_topic_bank():
    if TOPIC_BANK.exists():
        try:
            return json.loads(TOPIC_BANK.read_text(encoding='utf-8'))
        except:
            return []
    return []

def save_topic_bank(topics):
    TOPIC_BANK.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding='utf-8')

# ============================================================
# Reddit 트렌드 수집
# ============================================================
def fetch_reddit_trends():
    """Reddit에서 장건강 관련 핫 포스팅 수집"""
    topics = []
    subreddits = ["guthealth", "nutrition", "supplements", "healthyfood", "ibs"]

    headers = {"User-Agent": "NutriStack Lab/1.0"}

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                posts = r.json().get("data", {}).get("children", [])
                for post in posts:
                    title = post["data"].get("title", "")
                    score = post["data"].get("score", 0)
                    if score > 100:
                        topics.append({"title": title, "score": score, "source": f"reddit/r/{sub}"})
            time.sleep(1)
        except Exception as e:
            logging.warning(f"Reddit {sub} 수집 실패: {e}")

    logging.info(f"  Reddit 트렌드 {len(topics)}개 수집")
    return topics

# ============================================================
# Google Trends RSS 수집
# ============================================================
def fetch_google_trends():
    """Google Trends RSS에서 트렌드 키워드 수집"""
    topics = []
    try:
        url = "https://trends.google.com/trending/rss?geo=US"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            # 간단한 XML 파싱
            titles = re.findall(r'<title>(.*?)</title>', r.text)
            for title in titles[1:]:  # 첫 번째는 피드 제목
                topics.append({"title": title, "source": "google_trends"})
        logging.info(f"  Google Trends {len(topics)}개 수집")
    except Exception as e:
        logging.warning(f"Google Trends 수집 실패: {e}")
    return topics

# ============================================================
# 주제 관련성 체크
# ============================================================
def is_relevant(title):
    """장건강/음식/영양제 관련 여부 체크"""
    title_lower = title.lower()
    gut_keywords = [
        "gut", "digest", "probiotic", "prebiotic", "fiber", "fibre",
        "microbiome", "stomach", "bowel", "intestin", "colon",
        "bloat", "ibs", "leaky", "ferment", "bacteria", "inflammation",
        "supplement", "vitamin", "mineral", "nutrition", "food", "diet",
        "health", "wellness", "immune", "enzyme"
    ]
    return any(kw in title_lower for kw in gut_keywords)

# ============================================================
# 주제 생성 (트렌드 기반)
# ============================================================
def generate_topic_from_trend(trend_title):
    """트렌드 제목을 블로그 주제로 변환"""
    # 기본 템플릿
    templates = [
        "{keyword} and {food}: The Complete Guide",
        "Best Foods to Take With {keyword}",
        "{keyword} and {food} Synergy: What Science Says",
        "How {food} Boosts {keyword} Absorption",
        "{keyword} Protocol: Foods to Eat and Avoid",
        "The {keyword} and {food} Connection Explained",
        "{keyword} vs {food}: Which Works Better for Gut Health",
    ]
    return trend_title

# ============================================================
# 고정 주제 DB (트렌드 없을 때 폴백)
# ============================================================
FALLBACK_TOPICS = [
    # Probiotics + Foods
    {"p1": "Probiotics and Banana Synergy: Why Prebiotics Unlock Probiotic Power", "p2": "Probiotic Banana Protocol: The Complete Gut Microbiome Guide", "category": "PROBIOTIC_FOOD"},
    {"p1": "Probiotics and Garlic: The Prebiotic Powerhouse Combination", "p2": "Garlic Probiotic Stack: Nordic Gut Defense Protocol", "category": "PROBIOTIC_FOOD"},
    {"p1": "Probiotics and Oats: The Fiber-Bacteria Synergy Stack", "p2": "Oat Probiotic Protocol: Microbiome Optimization Guide", "category": "PROBIOTIC_FOOD"},
    {"p1": "Probiotics and Kefir: Doubling Your Gut Bacteria Diversity", "p2": "Kefir Probiotic Protocol: The Complete Fermented Food Guide", "category": "PROBIOTIC_FOOD"},
    {"p1": "Probiotics and Dark Chocolate: The Surprising Gut Health Stack", "p2": "Dark Chocolate Probiotic Protocol: Polyphenol Gut Defense", "category": "PROBIOTIC_FOOD"},

    # L-Glutamine + Foods
    {"p1": "L-Glutamine and Bone Broth: The Leaky Gut Repair Stack", "p2": "L-Glutamine Bone Broth Protocol: Complete Gut Healing Guide", "category": "LEAKY_GUT"},
    {"p1": "L-Glutamine and Cabbage: Why This Combination Heals Gut Lining", "p2": "L-Glutamine Cabbage Protocol: Nordic Gut Repair Guide", "category": "LEAKY_GUT"},
    {"p1": "L-Glutamine and Eggs: The Complete Gut Barrier Repair Stack", "p2": "L-Glutamine Egg Protocol: Gut Lining Restoration Guide", "category": "LEAKY_GUT"},

    # Digestive Enzymes + Foods
    {"p1": "Digestive Enzymes and Pineapple: Nature's Digestion Power Stack", "p2": "Enzyme Pineapple Protocol: Complete Digestion Optimization", "category": "ENZYME_FOOD"},
    {"p1": "Digestive Enzymes and Papaya: The Tropical Gut Healing Stack", "p2": "Papaya Enzyme Protocol: Natural Digestive Support Guide", "category": "ENZYME_FOOD"},
    {"p1": "Digestive Enzymes and Ginger: The Anti-Bloat Synergy Stack", "p2": "Ginger Enzyme Protocol: Nordic Digestive Defense Guide", "category": "ENZYME_FOOD"},

    # Omega-3 + Foods
    {"p1": "Omega-3 and Salmon: Why Food Sources Beat Supplements", "p2": "Omega-3 Salmon Protocol: Anti-Inflammatory Gut Guide", "category": "OMEGA_FOOD"},
    {"p1": "Omega-3 and Walnuts: The Brain-Gut Axis Optimization Stack", "p2": "Omega-3 Walnut Protocol: Gut Inflammation Defense Guide", "category": "OMEGA_FOOD"},
    {"p1": "Omega-3 and Flaxseed: The Complete Anti-Inflammation Stack", "p2": "Flaxseed Omega-3 Protocol: Gut Health Optimization Guide", "category": "OMEGA_FOOD"},

    # Magnesium + Foods
    {"p1": "Magnesium and Spinach: The Gut Motility Synergy Stack", "p2": "Magnesium Spinach Protocol: Digestive Movement Guide", "category": "MAG_FOOD"},
    {"p1": "Magnesium and Avocado: Why This Combination Fixes Constipation", "p2": "Magnesium Avocado Protocol: Complete Gut Motility Guide", "category": "MAG_FOOD"},
    {"p1": "Magnesium and Dark Chocolate: The Stress-Gut Connection Stack", "p2": "Magnesium Dark Chocolate Protocol: Gut Stress Relief Guide", "category": "MAG_FOOD"},

    # Zinc + Foods
    {"p1": "Zinc and Oysters: The Ultimate Gut Wall Repair Stack", "p2": "Zinc Oyster Protocol: Complete Gut Barrier Guide", "category": "ZINC_FOOD"},
    {"p1": "Zinc and Pumpkin Seeds: The Natural Gut Defense Stack", "p2": "Zinc Pumpkin Seed Protocol: Gut Immunity Guide", "category": "ZINC_FOOD"},

    # Vitamin D + Foods
    {"p1": "Vitamin D and Mushrooms: The Gut Immune Activation Stack", "p2": "Vitamin D Mushroom Protocol: Gut Immunity Optimization", "category": "VIT_D_FOOD"},
    {"p1": "Vitamin D and Fatty Fish: Why This Combination Transforms Gut Health", "p2": "Vitamin D Fatty Fish Protocol: Complete Gut Immune Guide", "category": "VIT_D_FOOD"},

    # Fiber + Supplements
    {"p1": "Psyllium Husk and Probiotics: The Fiber-Bacteria Power Stack", "p2": "Psyllium Probiotic Protocol: Microbiome Fiber Guide", "category": "FIBER_SUPP"},
    {"p1": "Inulin and Bifidobacteria: The Prebiotic Synergy Stack", "p2": "Inulin Bifidobacteria Protocol: Complete Prebiotic Guide", "category": "FIBER_SUPP"},
    {"p1": "Resistant Starch and Probiotics: The Gut Microbiome Stack", "p2": "Resistant Starch Protocol: Complete Microbiome Guide", "category": "FIBER_SUPP"},

    # Foods to Avoid
    {"p1": "Probiotics and Alcohol: Why This Combination Destroys Gut Bacteria", "p2": "Alcohol Gut Damage Protocol: Recovery and Repair Guide", "category": "AVOID"},
    {"p1": "Digestive Enzymes and Coffee: The Timing You're Getting Wrong", "p2": "Coffee Enzyme Protocol: Optimal Digestion Timing Guide", "category": "AVOID"},
    {"p1": "Probiotics and Antibiotics: The Survival Protocol You Need", "p2": "Antibiotic Probiotic Timing Protocol: Complete Recovery Guide", "category": "AVOID"},

    # Women's Gut Health
    {"p1": "Probiotics for Women: The Hormone-Gut Connection Explained", "p2": "Women's Probiotic Protocol: Hormone Balance Gut Guide", "category": "WOMENS"},
    {"p1": "Iron and Gut Health: Why Women's Digestion Suffers Most", "p2": "Women's Iron Gut Protocol: Complete Absorption Guide", "category": "WOMENS"},

    # Gut-Brain Axis
    {"p1": "Probiotics and Anxiety: The Gut-Brain Axis Science", "p2": "Probiotic Anxiety Protocol: Gut-Brain Optimization Guide", "category": "GUT_BRAIN"},
    {"p1": "L-Theanine and Gut Health: The Stress-Digestion Connection", "p2": "L-Theanine Gut Protocol: Stress Digestion Guide", "category": "GUT_BRAIN"},
]

# ============================================================
# 메인 트렌드 수집 + 주제 선정
# ============================================================
def run_trend_hunt():
    logging.info("🌿 NutriStack Lab Trend Hunter 시작")
    report_to_discord("🔍 트렌드 수집 시작...")

    used_topics = load_used_topics()
    bank = load_topic_bank()
    existing_topics = [t.get("p1", "") for t in bank]

    new_topics = []

    # 1. Reddit 트렌드 수집
    reddit_trends = fetch_reddit_trends()

    # 2. Google Trends 수집
    google_trends = fetch_google_trends()

    # 3. 관련 트렌드 필터링 + 주제 생성
    all_trends = reddit_trends + google_trends
    relevant = [t for t in all_trends if is_relevant(t["title"])]

    logging.info(f"  관련 트렌드 {len(relevant)}개 발견")

    # 4. 폴백 주제에서 미사용 항목 추가
    for topic in FALLBACK_TOPICS:
        p1 = topic["p1"]
        # 중복 체크
        is_used = any(p1.lower() in u.lower() or u.lower() in p1.lower() for u in used_topics)
        is_existing = any(p1 == t for t in existing_topics)

        if not is_used and not is_existing:
            bank.append({
                "p1": topic["p1"],
                "p2": topic["p2"],
                "category": topic["category"],
                "status": "pending",
                "date_added": datetime.now().strftime("%Y-%m-%d"),
                "source": "fallback"
            })
            new_topics.append(topic["p1"])

    save_topic_bank(bank)

    pending = [t for t in bank if t.get("status") == "pending"]
    logging.info(f"  ✅ 주제 은행: 총 {len(bank)}개 / 대기 {len(pending)}개")
    report_to_discord(f"✅ 트렌드 수집 완료!\n주제 은행: {len(pending)}개 대기 중")

    return bank

# ============================================================
# 오늘의 주제 선택
# ============================================================
def get_todays_topic():
    bank = load_topic_bank()
    used_topics = load_used_topics()

    # 대기 중인 주제 필터
    pending = [t for t in bank if t.get("status") == "pending"]

    if not pending:
        logging.info("  ♻️ 주제 소진 → 트렌드 재수집")
        run_trend_hunt()
        bank = load_topic_bank()
        pending = [t for t in bank if t.get("status") == "pending"]

    if not pending:
        logging.error("  ❌ 사용 가능한 주제 없음!")
        return None

    # 카테고리 다양성 고려
    if used_topics:
        last_used = used_topics[-1] if used_topics else ""
        last_topic = next((t for t in bank if t.get("p1", "") == last_used), None)
        last_category = last_topic.get("category", "") if last_topic else ""

        different = [t for t in pending if t.get("category") != last_category]
        if different:
            pending = different

    import random
    selected = random.choice(pending)

    # 상태 업데이트
    for t in bank:
        if t.get("p1") == selected["p1"]:
            t["status"] = "selected"
            t["date_selected"] = datetime.now().strftime("%Y-%m-%d")
            break

    save_topic_bank(bank)
    save_used_topic(selected["p1"])

    logging.info(f"  📌 오늘의 주제: [{selected['category']}] {selected['p1'][:50]}")
    return selected


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "hunt":
        run_trend_hunt()
    elif len(sys.argv) > 1 and sys.argv[1] == "today":
        topic = get_todays_topic()
        if topic:
            print(f"✅ 선택된 주제: {topic['p1']}")
    else:
        run_trend_hunt()
