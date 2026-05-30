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
            try:
                pytrends.build_payload(batch, timeframe=timeframe, geo='US')
                data = pytrends.interest_over_time()
                if not data.empty:
                    for kw in batch:
                        if kw in data.columns:
                            scores[kw] = int(data[kw].mean())
                time.sleep(1.5)
            except Exception as e:
                logging.warning(f"  Trends 배치 오류 [{timeframe}]: {e}")

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
    24시간 내 불규칙 발행 스케줄
    - 최소 3시간 간격
    - 06:00 ~ 22:00 범위
    - 분 단위 entropy (사람처럼 불규칙하게)
    """
    available = list(range(6, 22))
    chosen = []

    for _ in range(count):
        if not available: break
        h = random.choice(available)
        chosen.append(h)
        # ±3시간 제거
        available = [x for x in available if abs(x - h) > 3]

    chosen.sort()

    # 분 단위 불규칙성 (사람처럼)
    human_minutes = [0, 7, 11, 17, 23, 29, 33, 41, 47, 53]
    times = []
    for h in chosen:
        m = random.choice(human_minutes)
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
def create_raw_file(topic):
    """오케스트레이터가 감지할 .txt 파일 생성"""
    safe = "".join(c for c in topic if c.isalnum() or c in " -").strip()
    safe = safe.replace(" ", "_")[:80]
    filename = f"{safe}.txt"
    file_path = RAW_DIR / filename
    file_path.write_text(topic, encoding='utf-8')
    logging.info(f"  📄 RAW 파일 생성: {filename}")
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
    create_raw_file(topic)
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
    오늘의 발행 시간표 (v6.0 — 트렌드 기반 comprehensive guide 3개):

    131개 comprehensive guide 중 미완료 주제를
      1번째 포스팅: 7일 트렌드 1위
      2번째 포스팅: 30일 트렌드 1위
      3번째 포스팅: 1년 트렌드 1위
    이미 선정/발행된 주제는 2위, 3위... 로 밀림.
    """
    logging.info("\n" + "="*50)
    today = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"📅 발행 시간표 수립 (v6.0 Trend-Guided) — {today}")

    bank    = load_topic_bank()

    # 미완료 comprehensive guide (날짜 배정 전 + 오늘 이미 배정된 것 모두 포함)
    pending = [
        t for t in bank
        if t.get("type") == "comprehensive_guide"
        and t.get("status") == "pending"
    ]

    # 오늘 이미 배정된 항목은 제외 (중복 방지)
    already_today = {
        t["topic"] for t in bank
        if t.get("date") == today and t.get("status") == "pending"
    }
    pending = [t for t in pending if t["topic"] not in already_today]

    if not pending:
        logging.info("  ✅ 모든 comprehensive guide 완료 (또는 오늘 이미 배정 완료)!")
        return None

    logging.info(f"  📚 남은 comprehensive guide: {len(pending)}개")

    # 영양소명 추출 (트렌드 검색 키워드)
    nutrients = list(dict.fromkeys(_extract_nutrient(t["topic"]) for t in pending))

    # 3개 트렌드 윈도우 — 순서 = 발행 순서
    TREND_WINDOWS = [
        ("7d",  "now 7-d",       "1번째"),
        ("30d", "today 1-m",     "2번째"),
        ("1yr", "today 12-m",    "3번째"),
    ]

    trend_scores = {}
    for label, tf, _ in TREND_WINDOWS:
        scores = fetch_google_trends(nutrients, timeframe=tf, cache_hours=6)
        trend_scores[label] = scores
        if scores:
            top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            logging.info(f"  [{label}] TOP3: {[f'{n}({s})' for n, s in top3]}")
        else:
            logging.info(f"  [{label}] 트렌드 데이터 없음 — 순서 기반 선택")

    # 각 윈도우에서 미선정 1위 선택
    selected        = []   # [(entry_dict, trend_label, trend_window_name)]
    selected_topics = set()

    for label, _, slot_name in TREND_WINDOWS:
        scores = trend_scores[label]
        # 아직 선정 안 된 항목을 트렌드 점수 내림차순 정렬
        ranked = sorted(
            [t for t in pending if t["topic"] not in selected_topics],
            key=lambda t: (
                scores.get(_extract_nutrient(t["topic"]), 0),
                random.uniform(0, 1)   # 동점 시 랜덤 tiebreak
            ),
            reverse=True
        )
        if not ranked:
            logging.warning(f"  [{label}] 선택 가능한 주제 없음 — 스킵")
            continue
        chosen = ranked[0]
        nut    = _extract_nutrient(chosen["topic"])
        score  = scores.get(nut, 0)
        selected.append((chosen, label, slot_name))
        selected_topics.add(chosen["topic"])
        logging.info(f"  [{slot_name}/{label}] 선택: {chosen['topic']} (trend={score})")

    if not selected:
        logging.warning("  ⚠️ 선택된 주제 없음 — plan 중단")
        return None

    # 발행 시간 배정 (불규칙, 3시간 간격)
    times = generate_daily_schedule(len(selected))

    # topic_bank 업데이트 — 날짜 + 시간 배정
    updated = 0
    plan_posts = []
    for (entry, label, slot_name), t in zip(selected, times):
        for b in bank:
            if b["topic"] == entry["topic"] and b.get("status") == "pending":
                b["date"]         = today
                b["time"]         = t
                b["trend_window"] = label
                b["trend_slot"]   = slot_name
                updated += 1
                break
        plan_posts.append({
            "time":         t,
            "topic":        entry["topic"],
            "topic_type":   "comprehensive_guide",
            "trend_window": label,
            "trend_slot":   slot_name,
        })

    save_topic_bank(bank)

    plan = {
        "date":       today,
        "post_count": len(selected),
        "posts":      plan_posts,
    }
    (META_DIR / "daily_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    logging.info(f"\n  📋 오늘 발행 시간표 ({len(selected)}개):")
    for p in plan_posts:
        logging.info(f"    ⏰ {p['time']} [{p['trend_slot']}/{p['trend_window']}] → {p['topic']}")
    logging.info(f"  📊 진행률: {len([t for t in bank if t.get('type')=='comprehensive_guide' and t.get('status')=='completed'])} / 131 완료")
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

    # [v5.6] 오늘 pending 항목이 없으면 자동으로 plan_today() 호출
    today_pending = [e for e in bank if e.get("date") == today and e.get("status") == "pending"]
    if not today_pending:
        logging.info(f"  📅 오늘({today}) 스케줄 없음 → plan_today() 자동 실행")
        new_plan = plan_today()
        bank = load_topic_bank()  # plan_today가 topic_bank에 추가하므로 재로드

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
        jobs_to_cancel = [j for j in list(schedule.jobs)
                          if any(str(t).startswith('post_') for t in getattr(j, 'tags', []))]
        for j in jobs_to_cancel:
            schedule.cancel_job(j)
        register_today_schedule()

    # 매일 00:01 — topic_bank 재스캔
    schedule.every().day.at("00:01").do(_rescan_today)

    # 매일 06:05 — topic_ranker 실행 후 재스캔 (06:00 topic_ranker 완료 후)
    schedule.every().day.at("06:05").do(_rescan_today)

    # 오늘 계획 즉시 수립
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