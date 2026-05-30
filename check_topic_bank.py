import json
from pathlib import Path

data = json.loads(Path("20_Meta/topic_bank.json").read_text(encoding="utf-8"))
guides = [x for x in data if x.get("type") == "comprehensive_guide"]
completed = [x for x in guides if x.get("status") == "completed"]
print(f"completed: {len(completed)}개")
for x in completed:
    print(f"  - {x.get('topic', x.get('title', '?'))[:70]}")
