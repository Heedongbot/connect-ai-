"""
NutriStack Topic Ranker
매일 아침 실행 → 전체 pending 가이드 검색량 비교 → 오늘 3개 슬롯 배정
슬롯 1: 최근 7일 검색량 1위
슬롯 2: 최근 30일 검색량 1위
슬롯 3: 최근 1년 검색량 1위
"""

import json
import time
import random
import logging
from pathlib import Path
from datetime import date

BASE_DIR      = Path(__file__).parent
TOPIC_BANK    = BASE_DIR / "20_Meta" / "topic_bank.json"
TREND_HISTORY = BASE_DIR / "20_Meta" / "trend_history.json"

TIMEFRAMES  = ["now 7-d", "today 1-m", "today 12-m"]
SLOT_LABELS = ["7일", "30일", "1년"]
PIVOT_KW    = "vitamins"

# 파일 핸들러만 상세 로그, 콘솔은 깔끔하게
file_handler = logging.FileHandler("topic_ranker.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
    handlers=[file_handler, console_handler],
)


def extract_keyword(topic: str) -> str:
    return topic.replace(" Complete Guide", "").strip()


def generate_slot_times() -> list:
    """09:00~19:00 랜덤 시간 3개, 최소 90분 간격."""
    start = 9 * 60
    end   = 19 * 60
    gap   = 90
    t1 = random.randint(start, end - 2 * gap)
    t2 = random.randint(t1 + gap, end - gap)
    t3 = random.randint(t2 + gap, end)
    def fmt(m): return f"{m // 60:02d}:{m % 60:02d}"
    return [fmt(t1), fmt(t2), fmt(t3)]


def generate_longtail_keywords(topic: str) -> list:
    kw = extract_keyword(topic)
    return [
        f"{kw} benefits",
        f"{kw} side effects",
        f"{kw} dosage",
        f"{kw} benefits and side effects",
        f"best time to take {kw}",
        f"{kw} before bed",
        f"{kw} with food",
        f"{kw} for women",
        f"{kw} for men over 50",
        f"how much {kw} per day",
        f"{kw} deficiency symptoms",
        f"does {kw} really work",
        f"{kw} vs other supplements",
        f"what does {kw} do",
        f"{kw} supplement guide",
    ]


def get_all_scores(keywords: list, timeframe: str, label: str) -> dict:
    """전체 키워드 검색량 점수 반환 (3개씩 피벗 비교)."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logging.error("pytrends 미설치 — pip install pytrends")
        return {}

    pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
    scores   = {}
    total    = len(keywords)
    batches  = (total + 2) // 3

    for i in range(0, total, 3):
        batch     = keywords[i:i + 3]
        batch_num = i // 3 + 1
        pct       = int(batch_num / batches * 20)
        bar       = "█" * pct + "░" * (20 - pct)

        # 콘솔에는 진행바만 표시 (같은 줄 덮어쓰기)
        print(f"\r  [{label}] [{bar}] {batch_num}/{batches}", end="", flush=True)

        try:
            pytrends.build_payload([PIVOT_KW] + batch, timeframe=timeframe, geo="US")
            df = pytrends.interest_over_time()
            if not df.empty:
                pivot_avg = df[PIVOT_KW].mean() or 1
                for kw in batch:
                    if kw in df.columns:
                        scores[kw] = round((df[kw].mean() / pivot_avg) * 100, 1)
            # 상세 로그는 파일에만
            logging.debug(f"배치 {batch_num} 완료: {batch}")
        except Exception as e:
            logging.debug(f"배치 {batch_num} 오류: {e}")
            time.sleep(10)

        time.sleep(random.uniform(2, 4))

    print()  # 줄바꿈
    return scores


def rank_and_schedule() -> list:
    data  = json.loads(TOPIC_BANK.read_text(encoding="utf-8"))
    today = date.today().strftime("%Y-%m-%d")

    # ── 오늘 이미 배정됐으면 스킵 (하루 1회만 실행) ───────
    already_today = [
        x for x in data
        if x.get("type") == "comprehensive_guide"
        and x.get("date", "") == today
        and x.get("status") == "pending"
    ]
    if len(already_today) >= 3:
        print("=" * 55)
        print(f"  오늘({today}) 이미 배정 완료 — 스킵")
        for x in already_today:
            print(f"  {x['time']}  {x['topic']}")
        print("=" * 55)
        return []

    pending = [
        x for x in data
        if x.get("type") == "comprehensive_guide"
        and x.get("status") == "pending"
        and x.get("date", "") != today
    ]

    if len(pending) < 3:
        logging.warning(f"pending 가이드 부족 ({len(pending)}개)")
        return []

    keywords  = [extract_keyword(x["topic"]) for x in pending]
    slot_times = generate_slot_times()

    print("=" * 55)
    print("  NutriStack 오늘 포스팅 스케줄 배정")
    print(f"  후보: {len(pending)}개  |  슬롯: {slot_times[0]} / {slot_times[1]} / {slot_times[2]}")
    print("=" * 55)

    selected_keywords = set()
    results           = []
    all_scores        = {}  # 히스토리 저장용

    tf_key_map = {"now 7-d": "7d", "today 1-m": "30d", "today 12-m": "1y"}

    for timeframe, label, slot_time in zip(TIMEFRAMES, SLOT_LABELS, slot_times):
        scores = get_all_scores(keywords, timeframe, label)
        all_scores[tf_key_map[timeframe]] = scores  # 히스토리용 전체 점수 보존

        ranked = sorted(
            [(kw, s) for kw, s in scores.items() if kw not in selected_keywords],
            key=lambda x: x[1], reverse=True,
        )

        if not ranked:
            logging.warning(f"[{label}] 순위 계산 실패")
            continue

        best_kw, best_score = ranked[0]
        selected_keywords.add(best_kw)

        for item in data:
            if (
                extract_keyword(item.get("topic", "")) == best_kw
                and item.get("status") == "pending"
            ):
                item["date"]              = today
                item["time"]              = slot_time
                item["longtail_keywords"] = generate_longtail_keywords(item["topic"])
                item["trend_slot"]        = label
                results.append({"slot": label, "topic": item["topic"], "time": slot_time, "score": best_score})
                break

    TOPIC_BANK.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 트렌드 히스토리 저장 ─────────────────────────────
    history = {}
    if TREND_HISTORY.exists():
        try:
            history = json.loads(TREND_HISTORY.read_text(encoding="utf-8"))
        except Exception:
            pass
    history[today] = {
        "7d":  all_scores.get("7d", {}),
        "30d": all_scores.get("30d", {}),
        "1y":  all_scores.get("1y", {}),
        "scheduled": [{"slot": r["slot"], "topic": r["topic"], "score": r["score"]} for r in results],
    }
    TREND_HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  트렌드 데이터 저장 완료 → trend_history.json ({len(history)}일치 누적)")

    print()
    print("  오늘 포스팅 확정")
    print("-" * 55)
    for r in results:
        print(f"  [{r['slot']}]  {r['topic']}")
        print(f"         → {r['time']}  (트렌드 점수 {r['score']})")
    print("=" * 55)

    return results


if __name__ == "__main__":
    rank_and_schedule()
