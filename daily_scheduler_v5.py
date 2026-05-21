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
from datetime import datetime, timedelta
from pathlib import Path

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
def fetch_google_trends(keywords, cache_hours=12):
    """Google Trends 검색량 수집 (캐시 포함)"""
    if not HAS_PYTRENDS:
        return {}

    # 캐시 확인
    if TRENDS_CACHE.exists():
        try:
            cached = json.loads(TRENDS_CACHE.read_text(encoding='utf-8'))
            ct = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
            if (datetime.now() - ct).total_seconds() < cache_hours * 3600:
                logging.info(f"  📊 Trends 캐시 사용 ({len(cached.get('scores', {}))}개)")
                return cached.get("scores", {})
        except: pass

    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        scores = {}
        for i in range(0, min(len(keywords), 20), 5):
            batch = keywords[i:i+5]
            try:
                pytrends.build_payload(batch, timeframe='today 1-m', geo='US')
                data = pytrends.interest_over_time()
                if not data.empty:
                    for kw in batch:
                        if kw in data.columns:
                            scores[kw] = int(data[kw].mean())
                time.sleep(1.5)
            except Exception as e:
                logging.warning(f"  Trends 배치 오류: {e}")

        TRENDS_CACHE.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "scores": scores
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        logging.info(f"  📊 Google Trends 수집: {len(scores)}개")
        return scores
    except Exception as e:
        logging.warning(f"  Trends 오류: {e}")
        return {}

def get_trending_nutrients(top_n=15):
    """트렌딩 영양소 상위 N개 반환"""
    sample = random.sample(NUTRIENTS, min(25, len(NUTRIENTS)))
    scores = fetch_google_trends(sample)

    # 점수 없는 항목은 낮은 점수로
    all_scored = []
    for nut in NUTRIENTS:
        base_score = scores.get(nut, 0)
        # 약간의 랜덤성 추가 (너무 고정되지 않게)
        jitter = random.randint(0, 10)
        all_scored.append((base_score + jitter, nut))

    all_scored.sort(key=lambda x: x[0], reverse=True)
    top = [n for _, n in all_scored[:top_n]]

    # 랜덤 6개 추가 (다양성)
    extra = random.sample(NUTRIENTS, min(6, len(NUTRIENTS)))
    combined = list(dict.fromkeys(top + extra))  # 중복 제거, 순서 유지
    logging.info(f"  📈 트렌딩 TOP 5: {top[:5]}")
    return combined

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

def run_posting_job(topic_type):
    """스케줄된 포스팅 실행 (Just-In-Time 실시간 트렌드 스캔)"""
    logging.info("\n" + "="*50)
    logging.info(f"⏰ 포스팅 JIT 실행 시작 (타입: {topic_type})")
    
    # 1. 포스팅 실행 직전(JIT) 실시간 트렌드 수집
    logging.info("  🔍 실시간 트렌딩 영양소 스캔 중 (최신 데이터)...")
    trending = get_trending_nutrients(top_n=15)
    if not trending:
        trending = random.sample(NUTRIENTS, 15)
        
    # 2. 발행된 주제 로드 (중복 방지)
    published = load_published_topics()
    
    # 3. 실시간 트렌드를 반영한 주제 생성
    topic = generate_topic(topic_type, trending, published)
    logging.info(f"  🎯 JIT 최종 생성 주제: {topic}")
    
    # DB 기록용
    post_info = [{"time": datetime.now().strftime("%H:%M"), "topic": topic, "topic_type": topic_type}]
    add_to_topic_bank(post_info)
    save_schedule_log(post_info)

    # 4. 파일 던져서 오케스트레이터 깨우기
    create_raw_file(topic)
    mark_topic_done(topic)
    logging.info(f"  ✅ RAW 파일 생성 완료 → 오케스트레이터가 즉시 처리합니다!")
    logging.info("="*50)

# ============================================================
# 하루 계획 수립
# ============================================================
def plan_today():
    """
    오늘의 발행 시간표 계획 (JIT 모드):
    - 발행 수: 2~4개
    - 스케줄: 불규칙
    - 주제: (포스팅 직전 실시간 생성으로 위임)
    """
    logging.info("\n" + "="*50)
    logging.info(f"📅 오늘의 발행 시간표 수립 (JIT 모드) — {datetime.now().strftime('%Y-%m-%d')}")

    # 발행 수 결정
    post_count = random.choices([2, 3, 4], weights=[35, 45, 20], k=1)[0]
    logging.info(f"  🎲 오늘 발행 계획 수: {post_count}개")

    # 스케줄 시간 생성
    schedule_times = generate_daily_schedule(post_count)

    # 주제 타입 다양화 (타입만 미리 결정)
    type_weights = {
        "synergy": 20, "food-combo": 10, "side-effects": 8,
        "antagonism": 8, "recipe": 5, "mechanism": 8,
        "protocol": 10, "comparison": 8, "deficiency": 5, "timing": 5,
        "longtail-symptom": 15, "longtail-routine": 15, "longtail-mistake": 10,
    }
    selected_types = random.choices(
        list(type_weights.keys()), weights=list(type_weights.values()), k=post_count
    )
    
    # [v5.5] 매일 롱테일(Longtail) 키워드 1개 이상 강제 배정
    longtail_types = ["longtail-symptom", "longtail-routine", "longtail-mistake"]
    has_longtail = any(tt in longtail_types for tt in selected_types)
    if not has_longtail:
        # 랜덤한 인덱스 하나를 롱테일 타입으로 교체
        idx = random.randint(0, len(selected_types) - 1)
        selected_types[idx] = random.choice(longtail_types)
        logging.info(f"  🔍 롱테일 키워드 강제 주입: {selected_types[idx]}")

    # 연속 타입 방지
    for i in range(1, len(selected_types)):
        attempts = 0
        while selected_types[i] == selected_types[i-1] and attempts < 5:
            selected_types[i] = random.choices(
                list(type_weights.keys()), weights=list(type_weights.values()), k=1
            )[0]
            attempts += 1

    # JIT 시간표 구조 생성
    posts = []
    for t, tt in zip(schedule_times, selected_types):
        posts.append({
            "time":       t,
            "topic":      "[포스팅 직전 실시간 트렌드로 생성됨]",
            "topic_type": tt,
        })

    plan = {
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "post_count":  post_count,
        "posts":       posts,
        "trending":    [], # JIT 방식이므로 미리 수집 안함
    }
    plan_file = META_DIR / "daily_plan.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')

    logging.info(f"\n  📋 오늘의 발행 시간표 ({post_count}개):")
    for p in posts:
        logging.info(f"    ⏰ {p['time']} [{p['topic_type']}] (트렌드 실시간 반영 대기)")
    logging.info("="*50)
    return plan

# ============================================================
# 스케줄 등록
# ============================================================
def register_today_schedule():
    """오늘 계획을 schedule 라이브러리에 등록 — 이미 계획이 있으면 재사용"""
    if not HAS_SCHEDULE:
        logging.error("schedule 라이브러리 미설치!")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    plan_file  = META_DIR / "daily_plan.json"

    # ✅ 핵심 버그 수정: 오늘 계획이 이미 있으면 새로 만들지 않음
    plan = None
    if plan_file.exists():
        try:
            existing = json.loads(plan_file.read_text(encoding='utf-8'))
            if existing.get("date") == today_str:
                plan = existing
                logging.info(f"  ♻️ 오늘 계획 재사용 ({len(plan['posts'])}개) — 중복 생성 방지")
        except: pass

    if plan is None:
        plan = plan_today()

    for post in plan["posts"]:
        t        = post["time"]
        tt       = post["topic_type"]

        schedule.every().day.at(t).do(
            run_posting_job, topic_type=tt
        ).tag(f"post_{t}")

        logging.info(f"  ⏰ 등록: {t} [{tt}] → (포스팅 직전 실시간 주제 결정)")

def run_scheduler():
    """메인 스케줄러 루프"""
    if not HAS_SCHEDULE:
        logging.error("schedule 미설치 — pip install schedule")
        return

    logging.info("🤖 NutriStack Lab Daily Scheduler v5.0")
    logging.info("  📊 Google Trends 실시간 연동")
    logging.info("  🎲 Human Cadence Entropy 활성화")
    logging.info("  📂 10가지 주제 타입 랜덤 선택")
    logging.info("  ⏰ 24시간 2~4개 랜덤 발행")
    logging.info("="*50)

    # 매일 00:01 — 새 계획 수립
    schedule.every().day.at("00:01").do(lambda: (
        [schedule.cancel_job(job) for job in schedule.jobs if any(str(tag).startswith('post_') for tag in getattr(job, 'tags', []))],
        register_today_schedule()
    ))

    # 오늘 계획 즉시 수립
    register_today_schedule()

    last_day = datetime.now().day
    last_status_min = -1

    while True:
        schedule.run_pending()
        now = datetime.now()

        # 날짜 바뀌면 이전 스케줄 정리
        if now.day != last_day:
            for tag in schedule.jobs:
                if hasattr(tag, 'tags') and any('post_' in str(t) for t in tag.tags):
                    schedule.cancel_job(tag)
            last_day = now.day

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

        if cmd == "test":
            # 주제 생성 테스트
            logging.info("🧪 주제 생성 테스트")
            trending = get_trending_nutrients(10)
            published = load_published_topics()
            logging.info(f"  트렌딩: {trending[:5]}")
            logging.info(f"  발행된 주제 수: {len(published)}")
            print("\n생성된 주제 샘플:")
            for tt in list(TOPIC_TEMPLATES.keys()):
                topic = generate_topic(tt, trending, published)
                print(f"  [{tt:15s}] {topic}")

        elif cmd == "plan":
            # 오늘 계획 출력
            plan = plan_today()
            print(json.dumps(plan, ensure_ascii=False, indent=2))

        elif cmd == "now":
            # 즉시 1개 발행 (테스트용)
            trending = get_trending_nutrients(10)
            published = load_published_topics()
            tt = random.choice(list(TOPIC_TEMPLATES.keys()))
            topic = generate_topic(tt, trending, published)
            logging.info(f"  즉시 발행: [{tt}] {topic}")
            run_posting_job(topic, tt)

        elif cmd == "status":
            # 현재 상태 출력
            bank = load_topic_bank()
            pending = [t for t in bank if t.get("status") == "pending"]
            done = [t for t in bank if t.get("status") == "completed"]
            print(f"대기 중: {len(pending)}개")
            for t in pending[:5]:
                print(f"  ⏰ {t.get('time','?')} [{t.get('type','?')}] {t.get('topic','')[:50]}")
            print(f"완료: {len(done)}개")

        else:
            print(f"알 수 없는 명령어: {cmd}")
            print("사용법: python daily_scheduler_v5.py [test|plan|now|status]")
    else:
        run_scheduler()