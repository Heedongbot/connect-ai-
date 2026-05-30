"""topic_bank.json 중복 completed 항목 제거."""
import json
from pathlib import Path

bank_path = Path("20_Meta/topic_bank.json")
data = json.loads(bank_path.read_text(encoding="utf-8"))

# completed comprehensive_guide 항목 중 중복 제거
# 기준: topic 또는 title의 핵심 영양소명이 동일한 경우 나중 항목을 pending으로 리셋
guides_completed = [
    (i, x) for i, x in enumerate(data)
    if x.get("type") == "comprehensive_guide" and x.get("status") == "completed"
]

print(f"수정 전 completed: {len(guides_completed)}개")

# 핵심 키워드 추출 (소문자, 공백 제거)
def key(x):
    t = (x.get("topic") or x.get("title") or "").lower()
    # "vitamin b12 cobalamin" → "vitaminb12"
    import re
    # 영양소 핵심어만 추출
    t = re.sub(r"(complete guide|comprehensive guide|cobalamin)", "", t)
    t = re.sub(r"\s+", "", t)
    return t.strip()

seen = {}
to_reset = []

for i, x in guides_completed:
    k = key(x)
    if k in seen:
        # 중복 — 나중 항목(현재)을 pending으로
        to_reset.append((i, x.get("topic") or x.get("title")))
    else:
        seen[k] = i

for i, topic in to_reset:
    data[i]["status"] = "pending"
    print(f"  pending으로 리셋: [{i}] {topic}")

# 최종 확인
completed_after = sum(
    1 for x in data
    if x.get("type") == "comprehensive_guide" and x.get("status") == "completed"
)
print(f"수정 후 completed: {completed_after}개")

bank_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("저장 완료")
