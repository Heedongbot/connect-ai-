import json
from pathlib import Path

f = Path(__file__).parent / "20_Meta" / "topic_bank.json"
data = json.loads(f.read_text(encoding="utf-8"))

# 마지막 날짜 항목을 당겨옴
pending = [x for x in data if x.get("status") == "pending" and x.get("date","") > "2026-05-26"]
if pending:
    target = sorted(pending, key=lambda x: (x.get("date",""), x.get("time","")))[-1]
    print(f"당김: {target['topic']} ({target['date']} {target['time']} → 2026-05-26 14:34)")
    target["date"] = "2026-05-26"
    target["time"] = "14:34"

f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("완료")
