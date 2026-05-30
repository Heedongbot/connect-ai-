import json
from pathlib import Path
from datetime import datetime

f = Path(__file__).parent / "20_Meta" / "topic_bank.json"
data = json.loads(f.read_text(encoding="utf-8"))

pending = [x for x in data if x.get("status") == "pending"]
if not pending:
    print("pending 항목 없음")
    exit()

# 마지막 날짜에서 당겨옴 (중간 스케줄 안 깨짐)
pending_sorted = sorted(pending, key=lambda x: (x.get("date",""), x.get("time","")))
target = pending_sorted[-1]
print("트리거:", target["topic"])

raw_dir = Path(__file__).parent / "00_Raw"
safe = "".join(c for c in target["topic"] if c.isalnum() or c in " -").strip()
raw_name = safe.replace(" ", "_") + ".txt"
(raw_dir / raw_name).write_text(target["topic"], encoding="utf-8")
print("RAW 생성:", raw_name)

target["date"] = datetime.now().strftime("%Y-%m-%d")
target["status"] = "completed"
target["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("완료")
