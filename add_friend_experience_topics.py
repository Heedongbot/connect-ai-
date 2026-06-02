"""
friend_experience 토픽을 topic_bank에 추가.
각 영양소당 4개 템플릿 — 지인/친구/동료/헬스장 지인 시점.
"""
import json, sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime

META_DIR  = Path("20_Meta")
BANK_PATH = META_DIR / "topic_bank.json"
NOW       = datetime.now().strftime("%Y-%m-%d")

# ── 영양소 목록 (published_links 기준으로 이미 발행된 것 포함) ──────────
NUTRIENTS = [
    "Magnesium", "Zinc", "Vitamin D3", "Vitamin K2", "Omega-3",
    "Vitamin C", "Iron", "Calcium", "Selenium", "Iodine", "Copper",
    "Potassium", "Vitamin B12", "NMN", "Probiotics", "Berberine",
    "Citrulline", "Melatonin", "HMB", "SAMe", "Ginger", "Creatine",
    "Taurine", "Glutathione", "Niacin", "Ashwagandha", "CoQ10",
    "L-Theanine", "Collagen", "Rhodiola Rosea", "Lion's Mane",
    "Alpha-GPC", "Quercetin", "Resveratrol", "Turmeric", "Fish Oil",
]

# ── 지인 유형 ──────────────────────────────────────────────────────────
RELATIONS = [
    "My Friend",
    "My Colleague",
    "A Guy at My Gym",
    "My Partner",
    "My Roommate",
    "A Woman I Work With",
    "My Trainer",
    "Someone I Know",
]

# ── 제목 템플릿 (지인 경험 시점) ────────────────────────────────────────
TEMPLATES = [
    "{relation} Tried {nutrient} for a Month — Here's What They Noticed",
    "{relation} Started {nutrient} Before I Did — And What They Told Me Changed My Mind",
    "I Almost Talked {relation} Out of {nutrient} — Then This Happened",
    "{relation} Had Better Results with {nutrient} Than I Expected",
    "What {relation} Said About {nutrient} After Six Weeks",
    "{relation} Figured Out the {nutrient} Timing I'd Been Missing",
    "I Watched {relation} Go Through the Same {nutrient} Learning Curve",
    "{relation} Swears by {nutrient} — Here's Why I Finally Listened",
]

def generate_topics(nutrient: str, count: int = 4) -> list:
    topics = []
    used_templates = set()
    used_relations = set()
    shuffled_t = TEMPLATES[:]
    shuffled_r = RELATIONS[:]
    random.shuffle(shuffled_t)
    random.shuffle(shuffled_r)

    for tmpl in shuffled_t:
        if len(topics) >= count:
            break
        rel = next((r for r in shuffled_r if r not in used_relations), shuffled_r[0])
        used_relations.add(rel)
        used_templates.add(tmpl)
        title = tmpl.format(relation=rel, nutrient=nutrient)
        topics.append({
            "topic":     title,
            "type":      "friend_experience",
            "nutrients": [nutrient],
            "status":    "pending",
            "priority":  "medium",
            "added_at":  NOW,
        })
    return topics

# ── topic_bank 로드 ──────────────────────────────────────────────────
bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
existing_topics = {t.get("topic","").lower() for t in bank}

added = 0
for nutrient in NUTRIENTS:
    # 이미 해당 영양소 friend_experience가 2개 이상이면 스킵
    already = sum(
        1 for t in bank
        if t.get("type") == "friend_experience"
        and nutrient.lower() in [n.lower() for n in t.get("nutrients", [])]
    )
    if already >= 4:
        continue

    new_topics = generate_topics(nutrient, count=4 - already)
    for t in new_topics:
        if t["topic"].lower() not in existing_topics:
            bank.append(t)
            existing_topics.add(t["topic"].lower())
            added += 1

BANK_PATH.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 타입별 현황 출력 ──────────────────────────────────────────────────
types = {}
for t in bank:
    tp = t.get("type","?")
    types[tp] = types.get(tp, 0) + 1

sys.stdout.write(f"✅ friend_experience 토픽 {added}개 추가\n\n")
sys.stdout.write("topic_bank 현황:\n")
for k, v in sorted(types.items(), key=lambda x: -x[1]):
    sys.stdout.write(f"  {k}: {v}개\n")
sys.stdout.write(f"  총계: {len(bank)}개\n")
