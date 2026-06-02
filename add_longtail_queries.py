"""symptom_query + question_query 토픽 topic_bank에 추가."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime

META_DIR  = Path("20_Meta")
BANK_PATH = META_DIR / "topic_bank.json"
NOW       = datetime.now().strftime("%Y-%m-%d")

SYMPTOM_TOPICS = [
    # 에너지/피로
    {"topic": "Always Tired After Lunch — Here's What Finally Made a Difference for Me",         "nutrients": ["Iron", "Vitamin B12", "Magnesium"]},
    {"topic": "I Was Exhausted Every Morning No Matter How Much I Slept",                         "nutrients": ["Iron", "Vitamin D3", "Magnesium"]},
    {"topic": "Afternoon Energy Crash Every Day — What I Tried and What Actually Helped",         "nutrients": ["Magnesium", "Iron", "Vitamin B12"]},
    {"topic": "Constant Fatigue Even After Rest — The Supplement That Changed Things for Me",     "nutrients": ["Iron", "Vitamin D3", "Vitamin B12"]},
    # 수면
    {"topic": "Waking Up at 3am Every Night — What Finally Stopped It",                          "nutrients": ["Magnesium", "Melatonin"]},
    {"topic": "Can't Fall Asleep Even When Exhausted — My Three-Month Search for Answers",       "nutrients": ["Magnesium", "L-Theanine", "Melatonin"]},
    {"topic": "Why I'd Wake Up Feeling More Tired Than When I Went to Bed",                      "nutrients": ["Magnesium", "Iron", "Vitamin D3"]},
    # 브레인 포그
    {"topic": "Brain Fog Every Afternoon — What I Tried Before Finding What Worked",             "nutrients": ["Zinc", "Vitamin B12", "Iron"]},
    {"topic": "Couldn't Focus After Noon — What Changed When I Fixed This",                      "nutrients": ["Magnesium", "Vitamin B12", "Zinc"]},
    {"topic": "Forgetting Simple Things Mid-Sentence — The Supplement That Helped Me",           "nutrients": ["Vitamin B12", "Alpha-GPC"]},
    # 면역
    {"topic": "Getting Sick Every Single Winter — What I Changed and Why It Worked",             "nutrients": ["Zinc", "Vitamin C", "Vitamin D3"]},
    {"topic": "Catching Every Cold That Went Around — My Six-Month Immune Experiment",           "nutrients": ["Zinc", "Vitamin C"]},
    # 피부/머리카락
    {"topic": "Hair Thinning Suddenly at 30 — What My Testing Revealed",                        "nutrients": ["Zinc", "Iron", "Biotin"]},
    {"topic": "Skin Breaking Out in My 30s — The Mineral Connection I Didn't Expect",           "nutrients": ["Zinc", "Vitamin A"]},
    # 기분/불안
    {"topic": "Irritable for No Reason — The Supplement That Quietly Fixed It",                  "nutrients": ["Magnesium", "Zinc", "Vitamin B6"]},
    {"topic": "Low Mood in Winter Every Year — What Actually Helped Beyond the Basics",          "nutrients": ["Vitamin D3", "SAMe", "5-HTP"]},
    # 근육/관절
    {"topic": "Leg Cramps at Night — What Stopped Them After Months of Trying",                  "nutrients": ["Magnesium", "Potassium"]},
    {"topic": "Muscle Soreness That Wouldn't Go Away — What Changed My Recovery",               "nutrients": ["Magnesium", "HMB", "Creatine"]},
    # 소화
    {"topic": "Bloated After Every Meal — What I Figured Out After Three Months",               "nutrients": ["Probiotics", "Digestive Enzymes", "Ginger"]},
    {"topic": "Stomach Issues That Doctors Couldn't Explain — What Actually Helped",            "nutrients": ["Probiotics", "Berberine"]},
]

QUESTION_TOPICS = [
    # 타이밍/복용법
    {"topic": "Why Isn't My Zinc Supplement Working — What I Finally Figured Out",              "nutrients": ["Zinc"]},
    {"topic": "How Long Does Magnesium Actually Take to Work — My Honest Timeline",             "nutrients": ["Magnesium"]},
    {"topic": "Why Do I Feel Worse After Taking Iron — What's Actually Happening",              "nutrients": ["Iron"]},
    {"topic": "Can I Take Vitamin D Without Vitamin K2 — What I Learned",                      "nutrients": ["Vitamin D3", "Vitamin K2"]},
    {"topic": "Why Does Creatine Take So Long to Work — My First Four Weeks",                  "nutrients": ["Creatine"]},
    {"topic": "Should I Take Probiotics With Food or Without — What Made a Difference",        "nutrients": ["Probiotics"]},
    {"topic": "Why Does Vitamin B12 Give Me Energy on Some Days and Not Others",               "nutrients": ["Vitamin B12"]},
    # 조합/상호작용
    {"topic": "Can You Take Zinc and Copper at the Same Time — What I Found Out",              "nutrients": ["Zinc", "Copper"]},
    {"topic": "Magnesium and Melatonin Together — What Happened When I Combined Them",         "nutrients": ["Magnesium", "Melatonin"]},
    {"topic": "Taking Vitamin D and K2 Together — Why I Finally Started Doing This",           "nutrients": ["Vitamin D3", "Vitamin K2"]},
    {"topic": "Iron and Vitamin C — Why I Take Them Together Now",                             "nutrients": ["Iron", "Vitamin C"]},
    {"topic": "Creatine and Caffeine — What Actually Happens When You Stack Them",             "nutrients": ["Creatine"]},
    # 형태/브랜드
    {"topic": "Magnesium Glycinate vs Oxide — Why the Form Finally Mattered to Me",            "nutrients": ["Magnesium"]},
    {"topic": "Zinc Picolinate vs Gluconate — What the Difference Actually Felt Like",         "nutrients": ["Zinc"]},
    {"topic": "Methylcobalamin vs Cyanocobalamin B12 — Why I Switched Forms",                  "nutrients": ["Vitamin B12"]},
    # 부작용/경험
    {"topic": "Why Zinc Made Me Nauseous — What Fixed It",                                     "nutrients": ["Zinc"]},
    {"topic": "Iron Supplements and Constipation — What Finally Solved It for Me",             "nutrients": ["Iron"]},
    {"topic": "Why Melatonin Left Me Groggy — The Dose Change That Helped",                    "nutrients": ["Melatonin"]},
    # 언제 효과
    {"topic": "How Long Before You Feel Vitamin D Working — My Six-Week Log",                  "nutrients": ["Vitamin D3"]},
    {"topic": "Does NMN Actually Do Anything — Honest Notes After Three Months",               "nutrients": ["NMN"]},
]

bank    = json.loads(BANK_PATH.read_text(encoding="utf-8"))
existing = {t.get("topic","").lower() for t in bank}

added = 0
for entry, topic_type in [(SYMPTOM_TOPICS, "symptom_query"), (QUESTION_TOPICS, "question_query")]:
    for t in entry:
        if t["topic"].lower() not in existing:
            bank.append({
                "topic":     t["topic"],
                "type":      topic_type,
                "nutrients": t["nutrients"],
                "status":    "pending",
                "priority":  "high",
                "added_at":  NOW,
            })
            existing.add(t["topic"].lower())
            added += 1

BANK_PATH.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")

types = {}
for t in bank:
    tp = t.get("type","?")
    types[tp] = types.get(tp, 0) + 1

sys.stdout.write(f"✅ symptom_query + question_query {added}개 추가\n\n")
sys.stdout.write("topic_bank 전체:\n")
for k, v in sorted(types.items(), key=lambda x: -x[1]):
    sys.stdout.write(f"  {k:<30} {v}개\n")
sys.stdout.write(f"  총계: {len(bank)}개\n")
