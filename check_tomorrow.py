import json
from pathlib import Path
data = json.loads(Path(__file__).parent.joinpath("20_Meta/topic_bank.json").read_text(encoding="utf-8"))
tomorrow = [x for x in data if x.get("date") == "2026-05-26"]
print("내일(05-26) 스케줄:")
for x in tomorrow:
    status = x.get("status", "pending")
    print(f"  [{status}] {x.get('time')} {x.get('topic')}")
