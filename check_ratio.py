"""현재 발행된 포스팅의 템플릿 비율 확인"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

meta_dir = Path("20_Meta")

# topic_bank에서 completed 항목 확인
tb = json.loads((meta_dir / "topic_bank.json").read_text(encoding="utf-8"))
completed = [x for x in tb if x.get("status") == "completed" and x.get("type") == "comprehensive_guide"]

print(f"완료: {len(completed)}개\n")

# links_db에서 템플릿 정보 확인
links_files = list(meta_dir.glob("links_db*.json"))
if links_files:
    links = json.loads(links_files[0].read_text(encoding="utf-8"))
    templates = {}
    for post in links:
        t = post.get("template", post.get("archetype", "unknown"))
        templates[t] = templates.get(t, 0) + 1
    print("템플릿 분포:")
    for t, cnt in sorted(templates.items(), key=lambda x: -x[1]):
        print(f"  {t}: {cnt}개")
else:
    print("links_db 없음")

# 목표 비율 vs 실제
target = {
    "C_failure_to_fix": 0.30,
    "B_success_story":  0.25,
    "E_period_based":   0.20,
    "D_three_mistakes": 0.15,
    "F_journal":        0.05,
    "A_mechanism_first":0.05,
}
print(f"\n목표 비율 (131개 기준):")
for k, v in target.items():
    print(f"  {k}: {v*100:.0f}% ({int(v*131)}개 목표)")
