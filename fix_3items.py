"""H1 Complete Guide 제거 / Related 인간화 / og:description 영어 통일"""
import pickle, sys, io, re, html as html_lib
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

BASE_DIR = Path(__file__).parent
BLOG_ID   = "2812259517039331714"
COPPER_ID = "653447465802015470"
IRON_ID   = "1947968909150831484"

def get_service():
    with open(BASE_DIR / "token.pickle", "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

svc = get_service()

# ── Related posts 제목 매핑 (두 포스트 공통) ─────────────────
RELATED_TITLE_MAP = {
    "How to Use Ashwagandha effectively: A Simple Guide":
        "What Ashwagandha Actually Did for My Sleep and Stress",
    "Why Citrulline Malate Changed My Routine Completely":
        "Why I Added Citrulline Malate (And What Happened Next)",
    "Vitamin C: What I Found After Months of Testing (Complete Guide)":
        "Vitamin C: What Months of Testing Actually Taught Me",
    "The Complete Vitamin K2 (MK7) Guide: Science, Pairing, and Routine":
        "Vitamin K2 (MK7): What I Learned About Dosing and Stacking",
    "Magnesium Complete Guide: Benefits, Types, and Best Dosage":
        "Magnesium: Why Form Matters More Than I Expected",
}

def fix_related(html):
    for old, new in RELATED_TITLE_MAP.items():
        html = html.replace(f">{old}</a>", f">{new}</a>")
    return html


# ════════════════════════════════════════════════
# COPPER
# ════════════════════════════════════════════════
print("=== COPPER ===")
copper = svc.posts().get(blogId=BLOG_ID, postId=COPPER_ID).execute()
c = copper.get("content", "")
c_title  = copper.get("title", "")
c_labels = [l if isinstance(l, str) else l.get("name", "") for l in copper.get("labels", [])]

# 1) H1 — "Complete Guide:" 제거
old_h1 = "Copper Complete Guide: My Year of Experimenting With This Mineral"
new_h1 = "Copper: My Year of Experimenting With This Mineral"
if old_h1 in c:
    c = c.replace(old_h1, new_h1)
    print(f"1) H1 수정: '{new_h1}'")
else:
    print("1) H1 — 이미 수정됨")

# 2) Related posts 인간화
before = c
c = fix_related(c)
changed = sum(1 for o in RELATED_TITLE_MAP if RELATED_TITLE_MAP[o] in c)
print(f"2) Related posts 인간화: {changed}개 변경")

# 3) og:description 영어로 교체
old_desc_pattern = re.compile(r'(<meta property="og:description" content=")[^"]*(")', re.IGNORECASE)
new_desc = "I spent a year testing copper supplements before things clicked. Here's what I found — the timing, the combinations, and the mistakes I kept making."
if old_desc_pattern.search(c):
    c = old_desc_pattern.sub(lambda m: m.group(1) + new_desc + m.group(2), c)
    print(f"3) og:description 영어 변경 완료")
else:
    print("3) og:description 패턴 없음")

c = html_lib.unescape(c)
svc.posts().update(blogId=BLOG_ID, postId=COPPER_ID,
                   body={"title": c_title, "content": c, "labels": c_labels},
                   publish=False).execute()
print("Copper 완료\n")


# ════════════════════════════════════════════════
# IRON
# ════════════════════════════════════════════════
print("=== IRON ===")
iron = svc.posts().get(blogId=BLOG_ID, postId=IRON_ID).execute()
i = iron.get("content", "")
i_title  = iron.get("title", "")
i_labels = [l if isinstance(l, str) else l.get("name", "") for l in iron.get("labels", [])]

# 1) H1 — "Iron Complete:" → "Iron:" ("Complete Guide" 패턴은 없지만 "Complete" 단독도 제거)
old_h1_i = "Iron Complete: How I Actually Fixed My Energy (After Months of Failing)"
new_h1_i = "Iron: How I Actually Fixed My Energy (After Months of Failing)"
if old_h1_i in i:
    i = i.replace(old_h1_i, new_h1_i)
    # JSON-LD headline도 같이 수정
    i = i.replace(
        '"headline": "Iron Complete: How I Actually Fixed My Energy (After Months of Failing)"',
        f'"headline": "{new_h1_i}"'
    )
    # og:title도 수정
    i = re.sub(
        r'(og:title.*?content=")[^"]+(")',
        lambda m: m.group(1) + new_h1_i + m.group(2),
        i
    )
    # Blogger 포스트 타이틀도
    i_title = new_h1_i
    print(f"1) H1/JSON-LD/og:title/포스트제목 수정: '{new_h1_i}'")
else:
    print("1) H1 — 이미 수정됨")

# 2) Related posts 인간화
before = i
i = fix_related(i)
changed = sum(1 for o in RELATED_TITLE_MAP if RELATED_TITLE_MAP[o] in i)
print(f"2) Related posts 인간화: {changed}개 변경")

# 3) og:description — Iron은 이미 영어, 확인만
m = re.search(r'og:description.*?content="([^"]+)"', i)
print(f"3) og:description (이미 영어): {m.group(1)[:60] if m else '없음'}...")

i = html_lib.unescape(i)
svc.posts().update(blogId=BLOG_ID, postId=IRON_ID,
                   body={"title": i_title, "content": i, "labels": i_labels},
                   publish=False).execute()
print("Iron 완료\n")

print("=== 전체 완료 ===")
