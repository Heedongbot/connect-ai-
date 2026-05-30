"""
오늘 발행 3개 주제 선정 + 시간 배정
사용: python scripts/schedule_today.py 20:33 21:52 23:11
"""
import sys, json, re, random, logging, time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')

BASE_DIR = Path(__file__).parent.parent
META_DIR = BASE_DIR / "20_Meta"
TOPIC_BANK_FILE = META_DIR / "topic_bank.json"


def load_bank():
    return json.loads(TOPIC_BANK_FILE.read_text(encoding="utf-8-sig"))

def save_bank(bank):
    TOPIC_BANK_FILE.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")

def extract_nutrient(topic_str):
    return re.sub(r"\s*(complete\s+guide|guide)\s*$", "", topic_str, flags=re.I).strip()


def fetch_trends(nutrients, timeframe, cache_hours=6):
    cache_tag  = timeframe.replace(" ", "_").replace("-", "")
    cache_file = META_DIR / f"trends_cache_{cache_tag}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            ct = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
            if (datetime.now() - ct).total_seconds() < cache_hours * 3600:
                logging.info(f"  캐시 사용 [{timeframe}] {len(cached.get('scores', {}))}개")
                return cached.get("scores", {})
        except:
            pass

    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360)
        scores = {}
        for i in range(0, min(len(nutrients), 30), 5):
            batch = nutrients[i:i+5]
            try:
                pytrends.build_payload(batch, timeframe=timeframe, geo="US")
                data = pytrends.interest_over_time()
                if not data.empty:
                    for kw in batch:
                        if kw in data.columns:
                            scores[kw] = int(data[kw].mean())
                time.sleep(1.5)
            except Exception as e:
                logging.warning(f"  배치 오류 [{timeframe}]: {e}")

        cache_file.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "timeframe": timeframe,
            "scores": scores,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.info(f"  구글 트렌드 [{timeframe}] {len(scores)}개 수집")
        return scores
    except Exception as e:
        logging.warning(f"  pytrends 오류 [{timeframe}]: {e}")
        return {}


def main():
    # 시간 인자 (기본값)
    times = sys.argv[1:4] if len(sys.argv) >= 4 else ["20:33", "21:52", "23:11"]
    today = datetime.now().strftime("%Y-%m-%d")

    bank    = load_bank()
    pending = [
        t for t in bank
        if t.get("type") == "comprehensive_guide"
        and t.get("status") == "pending"
        and not t.get("date")
    ]

    logging.info(f"\n{'='*50}")
    logging.info(f"남은 comprehensive guide: {len(pending)}개")
    logging.info(f"배정 시간: {times[0]} / {times[1]} / {times[2]}")
    logging.info(f"{'='*50}")

    if not pending:
        logging.info("모든 가이드 완료됨!")
        return

    nutrients = list(dict.fromkeys(extract_nutrient(t["topic"]) for t in pending))

    # 3개 트렌드 윈도우
    WINDOWS = [
        ("7d",  "now 7-d",    "1번째", times[0]),
        ("30d", "today 1-m",  "2번째", times[1]),
        ("1yr", "today 12-m", "3번째", times[2]),
    ]

    trend_scores = {}
    for label, tf, slot, _ in WINDOWS:
        logging.info(f"\n[{slot}/{label}] 트렌드 수집 중...")
        scores = fetch_trends(nutrients, timeframe=tf)
        trend_scores[label] = scores
        if scores:
            top5 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
            logging.info(f"  TOP5: {[f'{n}({s})' for n, s in top5]}")
        else:
            logging.info("  (데이터 없음 — 순서 기반 선택)")

    # 각 윈도우에서 1위 선정 (중복 없이)
    selected        = []
    selected_topics = set()

    for label, tf, slot_name, sched_time in WINDOWS:
        scores = trend_scores[label]
        ranked = sorted(
            [t for t in pending if t["topic"] not in selected_topics],
            key=lambda t: (
                scores.get(extract_nutrient(t["topic"]), 0),
                random.uniform(0, 1),
            ),
            reverse=True,
        )
        if not ranked:
            logging.warning(f"[{label}] 선택 가능한 주제 없음")
            continue
        chosen = ranked[0]
        sc     = scores.get(extract_nutrient(chosen["topic"]), 0)
        selected.append((chosen, label, slot_name, sched_time))
        selected_topics.add(chosen["topic"])
        logging.info(f"\n✅ [{slot_name}/{label}] {sched_time} → {chosen['topic']} (score={sc})")

    # topic_bank 업데이트
    for entry, label, slot_name, sched_time in selected:
        for b in bank:
            if b["topic"] == entry["topic"] and b.get("status") == "pending":
                b["date"]         = today
                b["time"]         = sched_time
                b["trend_window"] = label
                b["trend_slot"]   = slot_name
                break

    save_bank(bank)

    logging.info(f"\n{'='*50}")
    logging.info(f"오늘 스케줄 확정 ({len(selected)}개):")
    for entry, label, slot_name, sched_time in selected:
        logging.info(f"  ⏰ {sched_time} [{slot_name}/{label}] {entry['topic']}")
    logging.info("재시작하면 자동 등록됩니다.")
    logging.info(f"{'='*50}\n")


if __name__ == "__main__":
    main()
