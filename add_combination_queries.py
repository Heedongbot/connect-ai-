"""
combination_query 자동 생성.
published_links.json에서 발행된 영양소 목록 추출
→ 2개씩 조합 가능한 것끼리 combination_query 토픽 생성.
새 글 발행 시마다 재실행하면 새 조합이 자동으로 추가됨.
"""
import json, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime
from itertools import combinations

BASE_DIR  = Path(__file__).parent
META_DIR  = BASE_DIR / "20_Meta"
BANK_PATH = META_DIR / "topic_bank.json"
NOW       = datetime.now().strftime("%Y-%m-%d")

# ── 제목 템플릿 ─────────────────────────────────────────────────────
TEMPLATES = [
    "Can You Take {a} and {b} Together — What I Found Out",
    "Taking {a} With {b} — What Changed When I Combined Them",
    "{a} and {b} Stack — My Six-Week Experiment",
    "The {a} + {b} Combination I Didn't Expect to Work",
    "Why I Started Pairing {a} With {b} (And What Happened)",
]

# ── 영양소 정규화: 제목에서 영양소명 추출 ───────────────────────────
NUTRIENT_ALIASES = {
    "vitamin d3": "Vitamin D3",
    "vitamin d":  "Vitamin D3",
    "vitamin k2": "Vitamin K2",
    "vitamin k":  "Vitamin K2",
    "vitamin c":  "Vitamin C",
    "vitamin b12":"Vitamin B12",
    "vitamin b6": "Vitamin B6",
    "vitamin a":  "Vitamin A",
    "vitamin e":  "Vitamin E",
    "magnesium":  "Magnesium",
    "zinc":       "Zinc",
    "iron":       "Iron",
    "copper":     "Copper",
    "selenium":   "Selenium",
    "melatonin":  "Melatonin",
    "creatine":   "Creatine",
    "hmb":        "HMB",
    "citrulline": "Citrulline",
    "probiotics": "Probiotics",
    "berberine":  "Berberine",
    "ginger":     "Ginger",
    "nmn":        "NMN",
    "same":       "SAMe",
    "sam-e":      "SAMe",
    "vitamin b12":"Vitamin B12",
    "taurine":    "Taurine",
    "glutathione":"Glutathione",
    "niacin":     "Niacin",
    "potassium":  "Potassium",
    "ashwagandha":"Ashwagandha",
    "l-theanine": "L-Theanine",
    "coq10":      "CoQ10",
    "omega-3":    "Omega-3",
    "fish oil":   "Omega-3",
    "collagen":   "Collagen",
    "biotin":     "Biotin",
}

def extract_nutrients_from_title(title: str) -> list[str]:
    """제목에서 영양소명 추출."""
    t = title.lower()
    found = []
    for alias, canonical in NUTRIENT_ALIASES.items():
        if alias in t and canonical not in found:
            found.append(canonical)
    return found

def extract_nutrients_from_post(post: dict) -> list[str]:
    """published_links 항목에서 영양소 목록 추출."""
    # nutrients 필드 있으면 우선 사용
    nutrients = post.get("nutrients", [])
    if nutrients:
        return [NUTRIENT_ALIASES.get(n.lower(), n) for n in nutrients]
    # 없으면 제목에서 추출
    title = post.get("title", "") or post.get("topic", "")
    return extract_nutrients_from_title(title)

# ── published_links에서 발행된 영양소 수집 ──────────────────────────
pl_path = META_DIR / "published_links.json"
pl      = json.loads(pl_path.read_text(encoding="utf-8"))

# 영양소 → 발행 편수 + 포스팅 정보
nutrient_posts: dict[str, list] = {}
for post in pl:
    topic_type = post.get("topic_type", "")
    # friend_experience 타입은 조합 대상에서 제외
    if topic_type == "friend_experience":
        continue
    nuts = extract_nutrients_from_post(post)
    for n in nuts:
        if n not in nutrient_posts:
            nutrient_posts[n] = []
        nutrient_posts[n].append(post.get("title", ""))

# 1편 이상 발행된 영양소만
published_nutrients = sorted([n for n, posts in nutrient_posts.items() if len(posts) >= 1])

sys.stdout.write(f"발행된 영양소 {len(published_nutrients)}개:\n")
for n in published_nutrients:
    sys.stdout.write(f"  - {n} ({len(nutrient_posts[n])}편)\n")
sys.stdout.write("\n")

# ── topic_bank 로드 + 기존 조합 확인 ────────────────────────────────
bank     = json.loads(BANK_PATH.read_text(encoding="utf-8"))
existing = {t.get("topic","").lower() for t in bank}

# 이미 조합된 쌍 확인 (topic_bank + published_links — friend_experience 제외)
existing_pairs: set[frozenset] = set()
for t in bank:
    if t.get("type") == "friend_experience":
        continue  # 지인 경험 포스팅은 조합 대상 아님
    nuts = [n.lower() for n in (t.get("nutrients") or [])]
    if len(nuts) >= 2:
        existing_pairs.add(frozenset(nuts[:2]))
for p in pl:
    if p.get("topic_type") == "friend_experience":
        continue  # 지인 경험 포스팅은 기존 조합에서 제외
    nuts = [n.lower() for n in (extract_nutrients_from_post(p))]
    if len(nuts) >= 2:
        existing_pairs.add(frozenset(nuts[:2]))

# ── 조합 생성 ───────────────────────────────────────────────────────
# 같은 카테고리보다 다른 카테고리 조합이 더 유용하므로 우선순위 부여
import random
from site_brain import _NUTRIENT_TO_CAT

new_topics  = []
seen_titles = set()
combo_count = 0

all_pairs = list(combinations(published_nutrients, 2))
# 다른 카테고리 조합 먼저
random.shuffle(all_pairs)
all_pairs.sort(
    key=lambda p: 0 if _NUTRIENT_TO_CAT.get(p[0].lower()) != _NUTRIENT_TO_CAT.get(p[1].lower()) else 1
)

for a, b in all_pairs:
    pair = frozenset([a.lower(), b.lower()])
    if pair in existing_pairs:
        continue

    # 템플릿 중 랜덤 1개 선택
    tmpl  = random.choice(TEMPLATES)
    title = tmpl.format(a=a, b=b)

    if title.lower() in existing or title.lower() in seen_titles:
        continue

    seen_titles.add(title.lower())
    existing_pairs.add(pair)

    new_topics.append({
        "topic":     title,
        "type":      "combination_query",
        "nutrients": [a, b],
        "status":    "pending",
        "priority":  "medium",
        "added_at":  NOW,
    })
    combo_count += 1

# topic_bank에 추가
bank.extend(new_topics)
BANK_PATH.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 결과 출력 ───────────────────────────────────────────────────────
sys.stdout.write(f"✅ combination_query {combo_count}개 추가\n\n")
sys.stdout.write("샘플 10개:\n")
for t in new_topics[:10]:
    sys.stdout.write(f"  [{t['nutrients'][0]} × {t['nutrients'][1]}] {t['topic']}\n")

# 전체 타입 현황
types = {}
for t in bank:
    tp = t.get("type","?")
    types[tp] = types.get(tp, 0) + 1
sys.stdout.write(f"\ntopic_bank 전체:\n")
for k, v in sorted(types.items(), key=lambda x: -x[1]):
    sys.stdout.write(f"  {k:<30} {v}개\n")
sys.stdout.write(f"  총계: {len(bank)}개\n")
