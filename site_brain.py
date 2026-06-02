"""
site_brain.py — v9.0
사이트 단위 의사결정 레이어.

기능:
  1. 카테고리 분류 (131개 영양소 → 7개 카테고리)
  2. Category Balance   — 카테고리 비율 감시
  3. Cluster Completeness — 영양소별 클러스터 완성도
  4. Topic Authority   — 영양소별 편수
  5. recommend()       — plan_today()에 주입할 추천

사용:
  from site_brain import SiteBrain
  brain = SiteBrain()
  recs = brain.recommend()  # → {"block": [...], "boost": [...], "advice": "..."}
"""

import json
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("SiteBrain")

BASE_DIR = Path(__file__).parent
META_DIR = BASE_DIR / "20_Meta"

# ══════════════════════════════════════════════════════════════════
# 1. 카테고리 택소노미
# ══════════════════════════════════════════════════════════════════
CATEGORY_MAP: dict[str, list[str]] = {
    "minerals": [
        "Magnesium", "Zinc", "Iron", "Copper", "Selenium", "Iodine",
        "Calcium", "Potassium", "Boron", "Manganese", "Chromium",
        "Molybdenum", "Phosphorus", "Silica",
    ],
    "vitamins": [
        "Vitamin C", "Vitamin D", "Vitamin D3", "Vitamin K2", "Vitamin K1",
        "Vitamin B12", "Vitamin A", "Vitamin E", "Niacin", "Vitamin B3",
        "Folate", "Biotin", "Vitamin B6", "Vitamin B1", "Vitamin B2",
        "Vitamin B5", "Vitamin B7", "Choline", "Inositol",
        "Pantothenic Acid", "Riboflavin", "Thiamine",
    ],
    "performance": [
        "Creatine", "HMB", "Citrulline", "L-Citrulline", "Beta-Alanine",
        "BCAA", "Leucine", "L-Carnitine", "Betaine", "L-Arginine",
        "L-Glutamine", "L-Lysine", "Ornithine", "Carnosine",
        "Acetyl-L-Carnitine", "Taurine",
    ],
    "sleep_stress": [
        "Melatonin", "L-Theanine", "GABA", "5-HTP", "Ashwagandha",
        "Valerian Root", "Passionflower", "Lemon Balm", "Chamomile",
        "Glycine", "Mucuna Pruriens",
    ],
    "gut_metabolism": [
        "Probiotics", "Prebiotics", "Digestive Enzymes", "Berberine",
        "Ginger", "Psyllium", "Inulin", "Milk Thistle", "Bromelain",
        "Serrapeptase", "SAMe",
    ],
    "longevity_antioxidants": [
        "NMN", "NAD", "CoQ10", "PQQ", "Resveratrol", "Quercetin",
        "Glutathione", "Alpha Lipoic Acid", "Astaxanthin", "Fisetin",
        "Apigenin", "Sulforaphane", "Urolithin A", "EGCG", "Pterostilbene",
        "Spermidine", "Grape Seed Extract", "Pine Bark Extract",
    ],
    "cognitive_mood": [
        "Alpha-GPC", "CDP-Choline", "Phosphatidylserine", "Lion's Mane",
        "Bacopa Monnieri", "Rhodiola Rosea", "Ginkgo Biloba", "Gotu Kola",
        "NAC", "Vitamin B12",
    ],
}

# 역방향 맵: 영양소명 → 카테고리
_NUTRIENT_TO_CAT: dict[str, str] = {}
for _cat, _nuts in CATEGORY_MAP.items():
    for _n in _nuts:
        _NUTRIENT_TO_CAT[_n.lower()] = _cat

# 카테고리 목표 비율 (합 = 100)
CATEGORY_TARGETS: dict[str, float] = {
    "minerals":              0.25,
    "vitamins":              0.20,
    "performance":           0.18,
    "sleep_stress":          0.12,
    "gut_metabolism":        0.10,
    "longevity_antioxidants":0.08,
    "cognitive_mood":        0.07,
}

# 클러스터 슬롯: 각 영양소에 기대하는 토픽 유형
CLUSTER_SLOTS = [
    "guide",          # 기본 가이드
    "timing",         # 복용 타이밍
    "dosage",         # 용량
    "mistake",        # 실수/경험담
    "synergy",        # 조합
]

# ══════════════════════════════════════════════════════════════════
# 2. SiteBrain 클래스
# ══════════════════════════════════════════════════════════════════
class SiteBrain:
    def __init__(self):
        self.published   = self._load_published()
        self.topic_bank  = self._load_topic_bank()
        self._cat_counts: dict[str, int] = {}
        self._nutrient_counts: dict[str, int] = {}
        self._compute()

    # ── 로드 ───────────────────────────────────────────────────────
    def _load_published(self) -> list:
        p = META_DIR / "published_links.json"
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _load_topic_bank(self) -> list:
        p = META_DIR / "topic_bank.json"
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    # ── 카테고리 분류 ──────────────────────────────────────────────
    def categorize(self, title: str, nutrients: list = None) -> str:
        """제목 또는 영양소 목록으로 카테고리 반환."""
        # nutrients 필드 우선
        if nutrients:
            for n in nutrients:
                cat = _NUTRIENT_TO_CAT.get(n.lower())
                if cat:
                    return cat
        # 제목 키워드 매칭
        title_l = title.lower()
        for n, cat in _NUTRIENT_TO_CAT.items():
            if n in title_l:
                return cat
        return "other"

    # ── 집계 계산 ──────────────────────────────────────────────────
    def _compute(self):
        self._cat_counts = {k: 0 for k in CATEGORY_MAP}
        self._cat_counts["other"] = 0
        self._nutrient_counts = {}

        for post in self.published:
            title     = post.get("title", "") or post.get("topic", "")
            nutrients = post.get("nutrients", [])
            cat       = self.categorize(title, nutrients)
            self._cat_counts[cat] = self._cat_counts.get(cat, 0) + 1

            # 영양소별 카운트
            for n in (nutrients or []):
                key = n.lower()
                self._nutrient_counts[key] = self._nutrient_counts.get(key, 0) + 1
            # nutrients 없으면 제목에서 추출
            if not nutrients:
                for n in _NUTRIENT_TO_CAT:
                    if n in title.lower():
                        self._nutrient_counts[n] = self._nutrient_counts.get(n, 0) + 1
                        break

    # ── 공개 메서드 ────────────────────────────────────────────────
    def category_balance(self) -> dict:
        """현재 카테고리 비율 vs 목표."""
        total = max(sum(self._cat_counts.values()), 1)
        result = {}
        for cat, target in CATEGORY_TARGETS.items():
            actual = self._cat_counts.get(cat, 0) / total
            result[cat] = {
                "count":  self._cat_counts.get(cat, 0),
                "actual": round(actual, 3),
                "target": target,
                "gap":    round(target - actual, 3),   # 양수 = 부족, 음수 = 과잉
            }
        return result

    def topic_authority(self) -> dict:
        """영양소별 편수. 3편 이상 = adequate, 미만 = weak."""
        result = {}
        for n, cnt in sorted(self._nutrient_counts.items(), key=lambda x: -x[1]):
            result[n] = {
                "count":  cnt,
                "status": "adequate" if cnt >= 3 else ("building" if cnt >= 1 else "missing"),
            }
        return result

    def cluster_completeness(self) -> dict:
        """영양소별 클러스터 슬롯 완성도."""
        # topic_bank에서 pending/completed 모두 포함
        bank_by_nutrient: dict[str, list] = {}
        for t in self.topic_bank:
            for n in (t.get("nutrients") or []):
                key = n.lower()
                bank_by_nutrient.setdefault(key, []).append(t.get("type",""))

        result = {}
        for n, cnt in self._nutrient_counts.items():
            bank_types = set(bank_by_nutrient.get(n, []))
            # 발행된 편수 + topic_bank pending 편수
            pending_cnt = sum(
                1 for t in self.topic_bank
                if n in [x.lower() for x in (t.get("nutrients") or [])]
                and t.get("status") == "pending"
            )
            filled  = cnt + pending_cnt
            pct     = min(filled / len(CLUSTER_SLOTS), 1.0)
            result[n] = {
                "published": cnt,
                "pending":   pending_cnt,
                "total":     filled,
                "target":    len(CLUSTER_SLOTS),
                "pct":       round(pct, 2),
                "status":    "complete" if pct >= 1.0 else ("building" if pct >= 0.4 else "weak"),
            }
        return result

    def recommend(self) -> dict:
        """plan_today()에 주입할 추천 반환."""
        balance  = self.category_balance()
        authority = self.topic_authority()

        # 과잉 카테고리 (실제 > 목표 × 1.5)
        block_cats = [
            cat for cat, d in balance.items()
            if d["actual"] > d["target"] * 1.5 and d["count"] >= 3
        ]
        # 부족 카테고리 (실제 < 목표 × 0.5)
        boost_cats = [
            cat for cat, d in sorted(balance.items(), key=lambda x: x[1]["gap"], reverse=True)
            if d["gap"] > 0.05
        ]
        # weak authority 영양소 (1편 이하)
        weak_nutrients = [
            n for n, d in authority.items()
            if d["status"] == "missing"
        ][:5]

        advice_parts = []
        if block_cats:
            advice_parts.append(f"AVOID categories: {block_cats}")
        if boost_cats:
            advice_parts.append(f"PRIORITIZE categories: {boost_cats[:3]}")
        if weak_nutrients:
            advice_parts.append(f"BOOST weak topics: {weak_nutrients}")

        return {
            "block_categories":  block_cats,
            "boost_categories":  boost_cats[:3],
            "weak_nutrients":    weak_nutrients,
            "advice":            " | ".join(advice_parts) or "balanced",
            "balance":           balance,
        }

    def report(self) -> str:
        """터미널 출력용 리포트."""
        balance   = self.category_balance()
        authority = self.topic_authority()
        cluster   = self.cluster_completeness()
        total     = sum(self._cat_counts.values())

        lines = [
            f"\n{'='*60}",
            f"  SITE BRAIN REPORT  (총 {total}편)",
            f"{'='*60}",
            "\n[카테고리 밸런스]",
        ]
        for cat, d in balance.items():
            bar   = "█" * int(d["actual"] * 40)
            tbar  = "░" * int(d["target"] * 40)
            flag  = "🔴과잉" if d["gap"] < -0.05 else ("🟡부족" if d["gap"] > 0.05 else "✅")
            lines.append(
                f"  {cat:<25} {d['count']:2}편 {d['actual']:5.1%} / 목표 {d['target']:.0%}  {flag}"
            )

        lines.append("\n[Topic Authority (발행편수)]")
        for n, d in list(authority.items())[:10]:
            icon = "✅" if d["status"] == "adequate" else ("🔵" if d["status"] == "building" else "⚠️")
            lines.append(f"  {icon} {n:<20} {d['count']}편")

        lines.append("\n[클러스터 완성도 (약한 것)]")
        weak = [(n,d) for n,d in cluster.items() if d["status"] != "complete"]
        for n, d in sorted(weak, key=lambda x: x[1]["pct"])[:8]:
            pct_bar = "█" * int(d["pct"] * 10) + "░" * (10 - int(d["pct"] * 10))
            lines.append(f"  {n:<20} [{pct_bar}] {d['pct']:.0%}  발행{d['published']} 예정{d['pending']}")

        recs = self.recommend()
        lines += [
            "\n[추천]",
            f"  BLOCK : {recs['block_categories'] or '없음'}",
            f"  BOOST : {recs['boost_categories'] or '없음'}",
            f"  WEAK  : {recs['weak_nutrients'] or '없음'}",
            "="*60,
        ]
        return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    brain = SiteBrain()
    sys.stdout.write(brain.report() + "\n")
