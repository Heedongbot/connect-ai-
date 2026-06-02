"""
NutriStack Lab — Daily Scheduler v5.0
========================================
베이스: v4.8 daily_scheduler.py
추가:
  - Google Trends 실시간 트렌드 수집
  - 10가지 주제 타입 (시너지/음식/부작용/반감/레시피/기전/프로토콜/비교/결핍/타이밍)
  - 24시간 2~4개 랜덤 발행
  - Human cadence entropy (불규칙 발행 시간)
  - published_links.json 기반 중복 방지
  - topic_bank.json 큐 관리
"""
import time
import json
import re
import random
import logging
import shutil
import subprocess
import sys
import socket
import psutil
from datetime import datetime, timedelta
from pathlib import Path

# 스케줄러 중복 실행 방지 (포트 19998 점유)
_scheduler_socket = None
def _ensure_single_scheduler():
    global _scheduler_socket
    try:
        _scheduler_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _scheduler_socket.bind(('127.0.0.1', 19998))
    except socket.error:
        sys.stdout.write("[중복 실행 방지] 스케줄러가 이미 실행 중입니다 (포트 19998). 종료합니다.\n")
        sys.stdout.flush()
        sys.exit(0)

_ensure_single_scheduler()

try:
    import schedule
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False
    print("⚠️ schedule 미설치 — pip install schedule")

try:
    from pytrends.request import TrendReq
    HAS_PYTRENDS = True
except ImportError:
    HAS_PYTRENDS = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('scheduler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR         = Path(__file__).parent
RAW_DIR          = BASE_DIR / "00_Raw"
META_DIR         = BASE_DIR / "20_Meta"
TOPIC_BANK_FILE  = META_DIR / "topic_bank.json"
LINKS_DB_FILE    = META_DIR / "published_links.json"
TRENDS_CACHE     = META_DIR / "trends_cache.json"
SCHEDULE_LOG     = META_DIR / "schedule_history.json"

RAW_DIR.mkdir(exist_ok=True)
META_DIR.mkdir(exist_ok=True)

# ============================================================
# 영양소 마스터 DB
# ============================================================
NUTRIENTS = [
    # 기본 미네랄
    "Magnesium", "Zinc", "Vitamin D3", "Vitamin K2", "Omega-3",
    "Vitamin C", "Iron", "Calcium", "Selenium", "Iodine", "Boron",
    # 아미노산
    "L-Theanine", "L-Glutamine", "L-Carnitine", "L-Tyrosine",
    "Glycine", "Taurine", "NAC",
    # 노트로픽
    "Alpha-GPC", "Creatine", "CDP-Choline", "Phosphatidylserine",
    "Lion's Mane", "Bacopa Monnieri", "Rhodiola Rosea", "Ashwagandha",
    # 항산화 / 장수
    "Quercetin", "Resveratrol", "CoQ10", "PQQ", "Glutathione",
    "Alpha Lipoic Acid", "Astaxanthin", "NMN", "Berberine",
    # 비타민
    "Vitamin B12", "Vitamin B6", "Folate", "Biotin", "Vitamin A",
    # 특수
    "Probiotics", "Collagen", "Glucosamine", "MSM", "Turmeric",
    "Ginger", "Elderberry", "Melatonin", "5-HTP", "GABA",
]

# 음식 DB
FOODS = [
    "Salmon", "Sardines", "Eggs", "Spinach", "Broccoli",
    "Blueberries", "Walnuts", "Almonds", "Avocado", "Olive Oil",
    "Green Tea", "Kefir", "Yogurt", "Sauerkraut", "Dark Chocolate",
    "Pumpkin Seeds", "Chia Seeds", "Flaxseeds", "Oats", "Sweet Potato",
    "Brazil Nuts", "Oysters", "Liver", "Bone Broth", "Kimchi",
    "Mushrooms", "Berries", "Garlic", "Beets",
]

# 주제 타입별 템플릿
TOPIC_TEMPLATES = {
    "synergy": [
        "{A} and {B} Synergy: The Nordic Protocol",
        "{A} and {B}: Why They Work Better Together",
        "Stacking {A} with {B}: Clinical Evidence",
        "{A} and {B}: The Complete Combination Guide",
        "{A} plus {B}: Dosage and Timing",
    ],
    "food-combo": [
        "{A} with {B}: The Absorption Stack",
        "Best Foods to Take With {A}",
        "{B} Enhances {A} Absorption: Here's Why",
        "{A} and {B}: The Natural Pairing",
        "Eating {B} With Your {A} Supplement",
    ],
    "side-effects": [
        "{A} Side Effects: What the Research Shows",
        "Too Much {A}: Warning Signs to Know",
        "{A} Interactions: What to Avoid",
        "Is {A} Safe Long-Term? The Real Data",
        "{A} Overdose Risk: Clinical Findings",
    ],
    "antagonism": [
        "Never Combine {A} and {B}: Here's Why",
        "{A} Blocks {B} Absorption: The Science",
        "Why {A} and {B} Cancel Each Other Out",
        "{A} and {B}: The Dangerous Combination",
        "Avoid This {A} Mistake With {B}",
    ],
    "recipe": [
        "The {A} Smoothie That Maximizes Absorption",
        "{B} and {A} Morning Stack Recipe",
        "How to Cook With {A} for Maximum Benefit",
        "The Nordic {A} Protocol Recipe",
        "{A}-Rich {B} Bowl for Daily Use",
    ],
    "mechanism": [
        "How {A} Actually Works in Your Body",
        "The Mechanism of {A}: A Deep Dive",
        "{A} and the Brain-Gut Axis: Explained",
        "What {A} Does to Your Mitochondria",
        "{A} and Hormones: The Connection",
    ],
    "protocol": [
        "The Complete {A} Protocol: Dosage and Timing",
        "{A} Loading Protocol: Does It Work?",
        "How to Cycle {A} for Maximum Effect",
        "Morning vs Evening: When to Take {A}",
        "The 30-Day {A} Optimization Protocol",
    ],
    "comparison": [
        "{A} vs {B}: Which Is More Effective?",
        "Comparing {A} and {B}: The Full Analysis",
        "{A} or {B}: Which Should You Choose?",
        "{A} vs {B}: Cost, Efficacy, Safety",
        "Head-to-Head: {A} vs {B}",
    ],
    "deficiency": [
        "Signs You're {A} Deficient",
        "{A} Deficiency: Symptoms You're Ignoring",
        "Why Nordic People Are Low in {A}",
        "Testing for {A} Deficiency: A Guide",
        "How to Fix {A} Deficiency Quickly",
    ],
    "timing": [
        "Best Time to Take {A}: Morning or Night?",
        "When to Take {A} for Maximum Absorption",
        "{A} Timing Protocol: What Research Says",
        "Circadian Rhythm and {A}: The Optimal Window",
        "Should You Take {A} With Food?",
    ],
    "longtail-symptom": [
        "Why {A} Makes Me Sleepy: The Science",
        "{A} Causing Bloating: Is It Normal?",
        "Weird Dreams After Taking {A}: Explained",
        "Why {A} Upset My Stomach",
        "{A} Making Me Anxious: What You Should Know",
    ],
    "longtail-routine": [
        "Taking {A} Twice a Day: My Results",
        "Best Food to Eat With {A}",
        "Taking {A} on an Empty Stomach: Good or Bad?",
        "{A} Before Workout: Does It Help?",
        "Can I Take {A} Every Day Forever?",
    ],
    "longtail-mistake": [
        "Common {A} Mistakes You're Making",
        "Why {A} Isn't Working For You",
        "Stop Taking {A} Like This",
        "The {A} Mistake That Ruins Absorption",
        "Taking {A} Before Bed: A Huge Mistake?",
    ],
}

# ============================================================
# 트렌드 수집
# ============================================================
def fetch_google_trends(keywords, timeframe='today 1-m', cache_hours=6):
    """Google Trends 검색량 수집 (timeframe 파라미터화, 캐시 포함)"""
    if not HAS_PYTRENDS:
        return {}

    # timeframe별 캐시 파일 분리
    cache_tag  = timeframe.replace(' ', '_').replace('-', '')
    cache_file = META_DIR / f"trends_cache_{cache_tag}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding='utf-8'))
            ct = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
            if (datetime.now() - ct).total_seconds() < cache_hours * 3600:
                logging.info(f"  📊 Trends 캐시 [{timeframe}] ({len(cached.get('scores', {}))}개)")
                return cached.get("scores", {})
        except: pass

    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        scores = {}
        kw_list = list(keywords)
        for i in range(0, len(kw_list), 5):
            batch = kw_list[i:i+5]
            wait = 2.0
            for attempt in range(3):
                try:
                    pytrends.build_payload(batch, timeframe=timeframe, geo='US')
                    data = pytrends.interest_over_time()
                    if not data.empty:
                        for kw in batch:
                            if kw in data.columns:
                                scores[kw] = int(data[kw].mean())
                    time.sleep(wait)
                    break
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str:
                        logging.warning(f"  Trends 429 [{timeframe}] — {wait*4:.0f}초 대기 후 재시도")
                        time.sleep(wait * 4)
                        wait = min(wait * 2, 30)
                    else:
                        logging.warning(f"  Trends 배치 오류 [{timeframe}]: {e}")
                        break

        cache_file.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "timeframe": timeframe,
            "scores": scores
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        logging.info(f"  📊 Google Trends [{timeframe}] {len(scores)}개 수집")
        return scores
    except Exception as e:
        logging.warning(f"  Trends 오류 [{timeframe}]: {e}")
        return {}

# ============================================================
# 주제 생성
# ============================================================
def load_published_topics():
    """발행된 주제/제목 세트 로드"""
    topics = set()
    if LINKS_DB_FILE.exists():
        try:
            db = json.loads(LINKS_DB_FILE.read_text(encoding='utf-8'))
            for e in db:
                topics.add(e.get("title", "").lower())
                topics.add(e.get("topic", "").lower())
        except: pass
    if TOPIC_BANK_FILE.exists():
        try:
            bank = json.loads(TOPIC_BANK_FILE.read_text(encoding='utf-8'))
            for t in bank:
                if isinstance(t, dict):
                    topics.add(t.get("topic", "").lower())
        except: pass
    return topics

def is_duplicate_topic(topic, published):
    stop = {"the","and","or","a","an","of","for","in","with","vs","is",
            "your","how","why","nordic","protocol","stack","guide"}
    t_w = set(re.sub(r'[^\w\s]', ' ', topic.lower()).split()) - stop
    for pub in published:
        p_w = set(re.sub(r'[^\w\s]', ' ', pub.lower()).split()) - stop
        if not t_w or not p_w: continue
        overlap = len(t_w & p_w) / max(len(t_w), len(p_w))
        if overlap >= 0.85:
            return True
    return False

def generate_topic(topic_type, nutrients, published, max_tries=20):
    """주제 타입 + 트렌딩 영양소로 주제 생성"""
    templates = TOPIC_TEMPLATES.get(topic_type, TOPIC_TEMPLATES["synergy"])

    for _ in range(max_tries):
        template = random.choice(templates)
        a = random.choice(nutrients)

        if "{B}" in template:
            if topic_type == "food-combo":
                b = random.choice(FOODS)
            elif topic_type in ["antagonism", "comparison", "synergy"]:
                b_pool = [n for n in nutrients if n != a]
                b = random.choice(b_pool) if b_pool else random.choice(NUTRIENTS)
            else:
                b_pool = [n for n in nutrients if n != a]
                b = random.choice(b_pool) if b_pool else random.choice(NUTRIENTS)
            topic = template.format(A=a, B=b)
        else:
            topic = template.format(A=a)

        if not is_duplicate_topic(topic, published):
            return topic

    # 최대 시도 초과 — 기본 생성
    a = random.choice(nutrients)
    b = random.choice([n for n in nutrients if n != a])
    return f"{a} and {b}: The Nordic Health Guide"

# ============================================================
# 스케줄 생성 (Human Entropy)
# ============================================================
def generate_daily_schedule(count):
    """
    07:00 ~ 22:30 범위, 최소 간격 보장, 사람처럼 불규칙한 분 단위.
    count=4 이상일 때 랜덤 탈락 방지 — 균등 분배 후 jitter 적용.
    """
    START, END = 7, 22.5        # 07:00 ~ 22:30
    total_hours = END - START   # 15.5시간

    # 최소 간격: count에 따라 동적으로 결정
    # count=2 → 4h, count=3 → 3h, count=4 → 2.5h
    min_gap = max(2.5, total_hours / (count + 1))

    # 균등 간격으로 기준점 생성 후 ±30분 jitter
    interval = total_hours / (count + 1)
    chosen = []
    for i in range(1, count + 1):
        base = START + interval * i
        jitter = random.uniform(-0.4, 0.4)  # ±24분
        h_float = base + jitter
        # 범위 클램프 + 앞 슬롯과 최소 간격 보장
        h_float = max(START + 0.1, min(END - 0.5, h_float))
        if chosen and h_float - chosen[-1] < min_gap:
            h_float = chosen[-1] + min_gap
        chosen.append(h_float)

    human_minutes = [7, 11, 17, 23, 29, 33, 41, 47, 53]
    times = []
    for h_float in chosen:
        h = int(h_float)
        m = random.choice(human_minutes)
        if h >= END: h = END - 1
        times.append(f"{h:02d}:{m:02d}")

    return times

# ============================================================
# 토픽 뱅크 관리
# ============================================================
def load_topic_bank():
    if TOPIC_BANK_FILE.exists():
        try: return json.loads(TOPIC_BANK_FILE.read_text(encoding='utf-8'))
        except: return []
    return []

def save_topic_bank(bank):
    TOPIC_BANK_FILE.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding='utf-8')

def add_to_topic_bank(posts):
    """오늘 계획된 포스팅을 topic_bank에 추가"""
    bank = load_topic_bank()
    for p in posts:
        bank.append({
            "topic":  p["topic"],
            "type":   p["topic_type"],
            "time":   p["time"],
            "date":   datetime.now().strftime("%Y-%m-%d"),
            "status": "pending"
        })
    save_topic_bank(bank)

def mark_topic_done(topic):
    """발행된 토픽을 completed로 마킹"""
    bank = load_topic_bank()
    for t in bank:
        if t.get("topic", "").lower() == topic.lower():
            t["status"] = "completed"
            t["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_topic_bank(bank)

# ============================================================
# 발행 실행
# ============================================================
def create_raw_file(topic, topic_type="comprehensive_guide"):
    """오케스트레이터가 감지할 .txt 파일 생성"""
    safe = "".join(c for c in topic if c.isalnum() or c in " -").strip()
    safe = safe.replace(" ", "_")[:80]
    filename = f"{safe}.txt"
    file_path = RAW_DIR / filename
    content = f"topic_type: {topic_type}\n{topic}"
    file_path.write_text(content, encoding='utf-8')
    logging.info(f"  📄 RAW 파일 생성: {filename} [type={topic_type}]")
    return file_path

def save_schedule_log(posts):
    log = []
    if SCHEDULE_LOG.exists():
        try: log = json.loads(SCHEDULE_LOG.read_text(encoding='utf-8'))
        except: pass
    log.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "posts": posts,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    log = log[-30:]  # 최근 30일만 유지
    SCHEDULE_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')

def run_posting_job(topic, topic_type="comprehensive_guide"):
    """스케줄된 포스팅 실행 (주제 이미 결정됨 — plan_today에서 선정)"""
    logging.info("\n" + "="*50)
    logging.info(f"⏰ 포스팅 실행: {topic}")
    create_raw_file(topic, topic_type=topic_type)
    mark_topic_done(topic)
    save_schedule_log([{
        "time":       datetime.now().strftime("%H:%M"),
        "topic":      topic,
        "topic_type": topic_type,
    }])
    logging.info(f"  ✅ RAW 파일 생성 완료 → 오케스트레이터가 즉시 처리합니다!")
    logging.info("="*50)

# ============================================================
# 하루 계획 수립
# ============================================================
def _extract_nutrient(topic_str: str) -> str:
    """'Magnesium Complete Guide' → 'Magnesium'"""
    return re.sub(r'\s*(complete\s+guide|guide)\s*$', '', topic_str, flags=re.I).strip()


def plan_today():
    """
    v8.2 — 06:00 실행
    comprehensive_guide: 트렌드 점수 기반 1~2개
    longtail (synergy/antagonism/timing/question): priority 기반 1개
    총 2~3개 → 07~20시 배정
    """
    logging.info("\n" + "="*50)
    today = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"📊 트렌드 기반 스케줄 수립 (v8.2) — {today}")

    bank = load_topic_bank()

    # ── 가이드 후보 (기존) ───────────────────────────────────────────
    pending = [
        t for t in bank
        if t.get("type") == "comprehensive_guide"
        and t.get("status") == "pending"
        and not t.get("date")
    ]

    # ── 롱테일 후보 (신규) ───────────────────────────────────────────
    longtail_types = {"synergy", "antagonism", "timing", "question", "comparison",
                      "combination_query", "symptom_query", "question_query"}
    pending_longtail = [
        t for t in bank
        if t.get("type") in longtail_types
        and t.get("status") == "pending"
        and not t.get("date")
    ]
    # priority: high 먼저, 같으면 추가일 오래된 것 먼저
    pending_longtail.sort(
        key=lambda t: (0 if t.get("priority") == "high" else 1,
                       t.get("added_at", ""))
    )

    if not pending and not pending_longtail:
        logging.info("  ✅ 배정 가능한 항목 없음")
        # 롱테일 자동 보충
        try:
            import longtail_pipeline as _lp
            logging.info("  🔄 롱테일 자동 보충 실행...")
            _lp.run_full_pipeline(run_suggest=False)
        except Exception as _e:
            logging.warning(f"  롱테일 보충 실패: {_e}")
        return None

    logging.info(f"  📚 후보: {len(pending)}개")

    # 영양소명 추출
    # ── 가이드: 트렌드 점수 산출 ────────────────────────────────────
    selected_guides = []
    combined = {}

    if pending:
        nutrients = list(dict.fromkeys(_extract_nutrient(t["topic"]) for t in pending))
        WINDOWS = [
            ("7d",  "now 7-d",    4),
            ("30d", "today 1-m",  3),
            ("3m",  "today 3-m",  2),
            ("1yr", "today 12-m", 1),
        ]
        for label, tf, weight in WINDOWS:
            scores = fetch_google_trends(nutrients, timeframe=tf, cache_hours=6)
            if scores:
                top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
                logging.info(f"  [{label}×{weight}] TOP3: {[f'{n}({s})' for n, s in top3]}")
            for nut, s in scores.items():
                combined[nut] = combined.get(nut, 0) + s * weight

        # ── [v9.0] Site Brain 40% 반영 ─────────────────────────────
        _NUTRIENT_TO_CAT_local = {}  # fallback: 빈 dict (scope 오류 방지)
        try:
            from site_brain import SiteBrain, _NUTRIENT_TO_CAT as _NUTRIENT_TO_CAT_local
            _brain   = SiteBrain()
            _recs    = _brain.recommend()
            _block   = set(_recs.get("block_categories", []))
            _boost   = set(_recs.get("boost_categories", []))
            logging.info(f"  🧠 [SiteBrain] BLOCK:{list(_block)} BOOST:{list(_boost)}")
        except Exception as _sb_err:
            logging.warning(f"  [SiteBrain] 로드 실패: {_sb_err}")
            _block, _boost = set(), set()

        def _site_score(t: dict) -> float:
            nut = _extract_nutrient(t["topic"]).lower()
            cat = _NUTRIENT_TO_CAT_local.get(nut, "other") if _boost or _block else "other"
            s   = combined.get(_extract_nutrient(t["topic"]), 0)
            # 카테고리 보정: block=-40점, boost=+20점
            if cat in _block: s -= 40
            if cat in _boost: s += 20
            return s

        ranked = sorted(
            pending,
            key=lambda t: (_site_score(t), random.uniform(0, 1)),
            reverse=True,
        )
        # 가이드는 하루 1~2개
        guide_count = min(random.randint(1, 2), len(ranked))
        selected_guides = ranked[:guide_count]
        logging.info(f"  📚 가이드 선택 {guide_count}개: {[t['topic'][:35] for t in selected_guides]}")

    # ── 롱테일: priority 순 2개 ────────────────────────────────────
    selected_longtail = []
    if pending_longtail:
        # 같은 타입 연속 방지: 첫 번째와 다른 타입 선택
        first = pending_longtail[0]
        second = next(
            (t for t in pending_longtail[1:] if t.get("type") != first.get("type")),
            pending_longtail[1] if len(pending_longtail) > 1 else None,
        )
        selected_longtail = [t for t in [first, second] if t]
        for lt in selected_longtail:
            logging.info(f"  🔗 롱테일: [{lt['type']}] {lt['topic'][:50]}")

    # ── friend_experience: 1:9 비율 엄격 관리 ────────────────────────
    # published_links 기준 personal(guide+longtail) vs friend_experience 비율 확인
    try:
        _pl_path = Path(__file__).parent / "20_Meta" / "published_links.json"
        _pl = json.loads(_pl_path.read_text(encoding="utf-8")) if _pl_path.exists() else []
        _personal_count = sum(1 for p in _pl if p.get("topic_type","") != "friend_experience")
        _friend_count   = sum(1 for p in _pl if p.get("topic_type","") == "friend_experience")
        # 엄격 비율: friend = personal × 9 (1:9)
        _friend_needed = max(0, _personal_count * 9 - _friend_count)
        logging.info(f"  📊 발행 비율 — personal:{_personal_count} friend:{_friend_count} (필요:{_friend_needed}) [목표 1:9]")
    except Exception as _e:
        _friend_needed = 0  # 기본값 — 비율 계산 실패 시 강제 선택 안 함
        logging.warning(f"  비율 계산 실패: {_e}")

    _pending_friend = [
        t for t in bank
        if t.get("type") == "friend_experience"
        and t.get("status") == "pending"
        and not t.get("date")
    ]
    random.shuffle(_pending_friend)

    # 비율 충족 시 0개, 부족 시 최대 4개 — 강제 선택 없음 (엄격 1:9)
    _friend_select_count = min(
        max(0, min(4, _friend_needed)),  # 비율 충족 시 0개
        len(_pending_friend)
    )
    selected_friend = _pending_friend[:_friend_select_count]
    for ft in selected_friend:
        logging.info(f"  👥 friend_experience: {ft['topic'][:55]}")

    selected = selected_guides + selected_longtail + selected_friend
    count    = len(selected)

    if count == 0:
        logging.info("  ✅ 선택된 항목 없음")
        return None

    # ── 시간 배정 (07:00~20:00, 간격 최소 2.5시간) ─────────────────
    times = generate_daily_schedule(count)

    plan_posts = []
    for entry, t in zip(selected, times):
        sc = round(combined.get(_extract_nutrient(entry["topic"]), 0), 1) if entry in selected_guides else 0
        for b in bank:
            if b["topic"] == entry["topic"] and b.get("status") == "pending" and not b.get("date"):
                b["date"]        = today
                b["time"]        = t
                b["trend_score"] = sc
                break
        plan_posts.append({
            "time":  t,
            "topic": entry["topic"],
            "type":  entry.get("type", ""),
            "trend_score": sc,
        })

    save_topic_bank(bank)

    plan = {"date": today, "post_count": count, "posts": plan_posts}
    (META_DIR / "daily_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logging.info(f"\n  📋 오늘 발행 시간표 ({count}개):")
    for p in plan_posts:
        tag = f"[{p['type']}]" if p.get("type") else ""
        logging.info(f"    ⏰ {p['time']} {tag} → {p['topic'][:45]}")
    done = len([t for t in bank if t.get("type") == "comprehensive_guide" and t.get("status") == "completed"])
    logging.info(f"  📊 가이드 진행률: {done} / 131")

    # ── 재고 임계값 체크 (가이드 < 10 OR 롱테일 < 10 → 통합 자동 보충) ────
    _GUIDE_THRESHOLD    = 10
    _LONGTAIL_THRESHOLD = 10
    longtail_types = {"synergy", "antagonism", "timing", "question", "comparison",
                      "combination_query", "symptom_query", "question_query"}
    remaining_guides = [
        t for t in bank
        if t.get("type") == "comprehensive_guide" and t.get("status") == "pending"
    ]
    remaining_longtail = [
        t for t in bank
        if t.get("type") in longtail_types and t.get("status") == "pending"
    ]
    logging.info(
        f"  📦 재고 — 가이드: {len(remaining_guides)}개 / 롱테일: {len(remaining_longtail)}개"
    )

    if (len(remaining_guides) < _GUIDE_THRESHOLD
            or len(remaining_longtail) < _LONGTAIL_THRESHOLD):
        logging.info(
            f"  ⚠️ 재고 부족 (가이드 {len(remaining_guides)} or 롱테일 {len(remaining_longtail)} < 10) "
            f"→ 통합 충전 시작 (가이드+롱테일+Google Suggest)"
        )
        try:
            import subprocess, sys
            subprocess.Popen(
                [sys.executable, str(BASE_DIR / "longtail_pipeline.py")],
                cwd=str(BASE_DIR),
            )
            logging.info("  🔄 longtail_pipeline.py 통합 충전 백그라운드 실행 중...")
        except Exception as _e:
            logging.warning(f"  통합 충전 실패: {_e}")

    logging.info("="*50)
    return plan

# ============================================================
# 스케줄 등록
# ============================================================
def register_today_schedule():
    """오늘 날짜 topic_bank 항목만 스케줄 등록 (날짜 불일치 항목은 절대 등록 안 함)"""
    if not HAS_SCHEDULE:
        logging.error("schedule 라이브러리 미설치!")
        return

    bank = load_topic_bank()
    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now()

    # v8.1: plan_today()는 06:00에만 실행. 00:01은 등록만 담당.
    today_pending = [e for e in bank if e.get("date") == today and e.get("status") == "pending"]
    if not today_pending:
        logging.info(f"  📅 오늘({today}) 배정된 스케줄 없음 (06:00 트렌드 확인 후 배정 예정)")

    registered = 0

    for entry in bank:
        if entry.get("status") != "pending":
            continue
        entry_date = entry.get("date", "")
        entry_time = entry.get("time", "")

        # 오늘 날짜 항목만 등록
        if entry_date != today:
            continue
        if not entry_time:
            continue

        # 이미 지난 시간이면 스킵
        try:
            scheduled_dt = datetime.strptime(f"{entry_date} {entry_time}", "%Y-%m-%d %H:%M")
        except:
            continue
        topic = entry.get("topic", "")

        if scheduled_dt < now:
            # 지나간 시간 — 스케줄러 재시작으로 놓친 발행 즉시 실행
            logging.info(f"  ⚡ 시간 경과 → 즉시 실행: {entry_time} → {topic[:40]}")
            _trigger_topic(topic=topic)
            registered += 1
            continue

        schedule.every().day.at(entry_time).do(
            _trigger_topic, topic=topic
        ).tag(f"post_{entry_time}")
        logging.info(f"  ⏰ 등록: {entry_time} [comprehensive-guide] → {topic[:50]}")
        registered += 1

    if registered == 0:
        logging.info(f"  📭 오늘({today}) topic_bank 등록 항목 없음")
    else:
        logging.info(f"  ✅ topic_bank 항목 {registered}개 스케줄 등록 완료")

def _trigger_topic(topic):
    """topic_bank 항목을 00_Raw에 파일로 던져 오케스트레이터 트리거"""
    logging.info(f"\n{'='*50}")
    logging.info(f"⏰ topic_bank 트리거: {topic}")
    create_raw_file(topic)
    mark_topic_done(topic)
    logging.info(f"  ✅ RAW 파일 생성 완료 → 오케스트레이터 처리 대기")
    logging.info("="*50)

ORCHESTRATOR_SCRIPT   = BASE_DIR / "00_NutriStack_Grand_Orchestrator_v5.py"
HERNEX_SCRIPT         = BASE_DIR / "hernex_agent.py"
DISCORD_BOT_SCRIPT    = BASE_DIR / "bot_start.py"
MORNING_REPORT_SCRIPT = BASE_DIR / "morning_report.py"
_orch_proc = None  # 워치독이 관리하는 오케스트레이터 프로세스

def _is_orchestrator_running():
    """포트 19999 점유 여부로 오케스트레이터 생존 확인 (수동 시작도 감지)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 19999))
        s.close()
        return False  # 바인딩 성공 = 포트 비어있음 = 오케스트레이터 없음
    except OSError:
        return True   # 바인딩 실패 = 포트 사용 중 = 오케스트레이터 실행 중

def _is_discord_bot_running():
    """포트 19997 점유 여부로 디스코드봇 생존 확인."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 19997))
        s.close()
        return False
    except OSError:
        return True

def _is_hernex_running():
    """psutil cmdline으로 hernex_agent.py 생존 확인."""
    for p in psutil.process_iter(['cmdline']):
        try:
            if any('hernex_agent.py' in (c or '') for c in (p.info['cmdline'] or [])):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def _start_orchestrator():
    """오케스트레이터를 새 콘솔 창으로 시작."""
    global _orch_proc
    try:
        _orch_proc = subprocess.Popen(
            ["cmd", "/k", sys.executable, str(ORCHESTRATOR_SCRIPT)],
            cwd=str(BASE_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        logging.info(f"  [워치독] 오케스트레이터 시작 (창 모드) — PID {_orch_proc.pid}")
    except Exception as e:
        logging.error(f"  [워치독] 오케스트레이터 시작 실패: {e}")

def _start_hernex():
    """hernex_agent.py 백그라운드 재시작."""
    try:
        proc = subprocess.Popen(
            [sys.executable, str(HERNEX_SCRIPT)],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logging.info(f"  [워치독] hernex_agent 시작 — PID {proc.pid}")
    except Exception as e:
        logging.error(f"  [워치독] hernex_agent 시작 실패: {e}")

def _start_discord_bot():
    """bot_start.py 백그라운드 재시작."""
    try:
        proc = subprocess.Popen(
            [sys.executable, str(DISCORD_BOT_SCRIPT)],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logging.info(f"  [워치독] 디스코드봇 시작 — PID {proc.pid}")
    except Exception as e:
        logging.error(f"  [워치독] 디스코드봇 시작 실패: {e}")

def _is_morning_report_running():
    """포트 19993 점유 여부로 morning_report.py 생존 확인."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 19993))
        s.close()
        return False
    except OSError:
        return True

def _start_morning_report():
    """morning_report.py 백그라운드 재시작."""
    try:
        proc = subprocess.Popen(
            [sys.executable, str(MORNING_REPORT_SCRIPT)],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logging.info(f"  [워치독] morning_report 시작 — PID {proc.pid}")
    except Exception as e:
        logging.error(f"  [워치독] morning_report 시작 실패: {e}")


def run_scheduler():
    """메인 스케줄러 루프"""
    if not HAS_SCHEDULE:
        logging.error("schedule 미설치 — pip install schedule")
        return

    logging.info("🤖 NutriStack Lab Daily Scheduler v5.0")
    logging.info("  📋 topic_bank.json 전용 모드 (랜덤 JIT 생성 비활성)")
    logging.info("  🔁 워치독: 오케스트레이터 + hernex + 디스코드봇 + morning_report 자동 재시작")
    logging.info("="*50)

    def _rescan_today():
        """00:01 — 기존 등록된 스케줄만 재등록 (plan_today 호출 없음)"""
        jobs_to_cancel = [j for j in list(schedule.jobs)
                          if any(str(t).startswith('post_') for t in getattr(j, 'tags', []))]
        for j in jobs_to_cancel:
            schedule.cancel_job(j)
        register_today_schedule()

    def _plan_and_register():
        """06:00 — 트렌드 확인 + 점수 계산 + 오늘 스케줄 배정 + 등록"""
        plan_today()
        _rescan_today()

    # 00:01 — 스케줄 등록 (시간 배정 없음, 이미 배정된 것만 등록)
    schedule.every().day.at("00:01").do(_rescan_today)

    # 06:00 — 트렌드 확인 + 오늘 발행 주제 선택 + 시간 배정 + 등록
    schedule.every().day.at("06:00").do(_plan_and_register)

    # 시작 시 기존 스케줄 등록 (재시작 복구)
    register_today_schedule()

    # 워치독: 오케스트레이터 초기 시작
    _start_orchestrator()

    last_day = datetime.now().day
    last_status_min = -1
    last_watchdog_check = 0

    while True:
        schedule.run_pending()
        now = datetime.now()

        # 워치독: 60초마다 오케스트레이터 + 봇 생존 확인
        if time.time() - last_watchdog_check > 60:
            pause_flag = BASE_DIR.parent / "queue" / "watchdog.pause"
            if pause_flag.exists():
                logging.info("  ⏸️  [워치독] 일시정지 (watchdog.pause 존재) — 오케스트레이터 재시작 안 함")
            elif not _is_orchestrator_running():
                logging.warning("  ⚠️ [워치독] 오케스트레이터 꺼짐 감지 → 자동 재시작")
                _start_orchestrator()
            # 봇은 pause_flag 무관하게 항상 감시
            if not _is_hernex_running():
                logging.warning("  ⚠️ [워치독] hernex_agent 꺼짐 감지 → 자동 재시작")
                _start_hernex()
            if not _is_discord_bot_running():
                logging.warning("  ⚠️ [워치독] 디스코드봇 꺼짐 감지 → 자동 재시작")
                _start_discord_bot()
            if not _is_morning_report_running():
                logging.warning("  ⚠️ [워치독] morning_report 꺼짐 감지 → 자동 재시작")
                _start_morning_report()
            last_watchdog_check = time.time()

        # 날짜 바뀌면 이전 스케줄 정리 후 오늘 것 재등록
        if now.day != last_day:
            for job in list(schedule.jobs):
                if hasattr(job, 'tags') and any('post_' in str(t) for t in job.tags):
                    schedule.cancel_job(job)
            last_day = now.day
            logging.info(f"  📅 날짜 변경 감지 → 새 스케줄 등록")
            register_today_schedule()

        # 매 30분마다 상태 출력
        if now.minute % 30 == 0 and now.minute != last_status_min:
            next_job = schedule.next_run()
            if next_job:
                diff = next_job - now
                h, rem = divmod(int(diff.total_seconds()), 3600)
                m, _ = divmod(rem, 60)
                logging.info(f"  💤 다음 발행까지 {h}시간 {m}분")
            last_status_min = now.minute

        time.sleep(10)


# ============================================================
# CLI 명령어
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "plan":
            # 오늘 계획 수립 + 출력
            plan = plan_today()
            if plan:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print("계획 수립 실패 또는 모든 가이드 완료")

        elif cmd == "status":
            # 현재 상태 출력
            bank  = load_topic_bank()
            guides    = [t for t in bank if t.get("type") == "comprehensive_guide"]
            done      = [t for t in guides if t.get("status") == "completed"]
            pending   = [t for t in guides if t.get("status") == "pending"]
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_sch = [t for t in pending if t.get("date") == today_str]
            print(f"\n=== Comprehensive Guide 진행 현황 ===")
            print(f"완료: {len(done)} / 131")
            print(f"남은 가이드: {len(pending)}개")
            print(f"오늘 예정: {len(today_sch)}개")
            if today_sch:
                for t in today_sch:
                    print(f"  ⏰ {t.get('time','?')} [{t.get('trend_window','?')}] {t.get('topic','')[:60]}")
            print(f"\n다음 대기 5개:")
            for t in pending[:5]:
                print(f"  [{t.get('date','미배정'):10s}] {t.get('topic','')[:60]}")

        elif cmd == "trends":
            # 트렌드 미리보기 (실제 배정 없이)
            bank    = load_topic_bank()
            pending = [t for t in bank if t.get("type") == "comprehensive_guide" and t.get("status") == "pending"]
            nutrients = list(dict.fromkeys(_extract_nutrient(t["topic"]) for t in pending))
            print(f"남은 {len(pending)}개 가이드 트렌드 점수:")
            for label, tf, slot in [("7d","now 7-d","1번째"), ("30d","today 1-m","2번째"), ("1yr","today 12-m","3번째")]:
                scores = fetch_google_trends(nutrients, timeframe=tf, cache_hours=1)
                ranked = sorted(
                    [(scores.get(_extract_nutrient(t["topic"]), 0), t["topic"]) for t in pending],
                    reverse=True
                )[:5]
                print(f"\n[{slot}/{label}] TOP5:")
                for sc, tp in ranked:
                    print(f"  {sc:3d}  {tp}")

        else:
            print(f"알 수 없는 명령어: {cmd}")
            print("사용법: python daily_scheduler_v5.py [plan|status|trends]")
    else:
        run_scheduler()