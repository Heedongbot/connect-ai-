import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

data = json.loads(Path("20_Meta/published_links.json").read_text(encoding="utf-8"))
print(f"총 {len(data)}개\n")

templates = {}
for p in data:
    t = p.get("template") or p.get("archetype") or "unknown"
    templates[t] = templates.get(t, 0) + 1
    title = p.get("title", "")[:55]
    print(f"  [{t[:20]}] {title}")

print("\n--- 템플릿 분포 ---")
for t, cnt in sorted(templates.items(), key=lambda x: -x[1]):
    pct = cnt / len(data) * 100
    print(f"  {t}: {cnt}개 ({pct:.0f}%)")

target = {
    "C_failure_to_fix": 0.30,
    "B_success_story":  0.25,
    "E_period_based":   0.20,
    "D_three_mistakes": 0.15,
    "F_journal":        0.05,
    "A_mechanism_first":0.05,
}
print("\n--- 목표 대비 현재 ---")
for k, v in target.items():
    actual = templates.get(k, 0)
    goal_pct = v * 100
    actual_pct = actual / len(data) * 100 if data else 0
    gap = actual_pct - goal_pct
    sign = "▲" if gap > 5 else ("▼" if gap < -5 else "✓")
    print(f"  {sign} {k}: 목표 {goal_pct:.0f}% → 현재 {actual_pct:.0f}% ({actual}개)")
