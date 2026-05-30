"""Iron + Copper 포스트 최종 수정"""
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

# ────────────────────────────────────────────────
# COPPER 수정
# ────────────────────────────────────────────────
print("=== COPPER 수정 중 ===")
copper = svc.posts().get(blogId=BLOG_ID, postId=COPPER_ID).execute()
c_html  = copper.get("content", "")
c_title = copper.get("title", "")
c_labels = [l if isinstance(l, str) else l.get("name", "") for l in copper.get("labels", [])]

print(f"원본 길이: {len(c_html)}")

# 1) "The Real Talk" → "Key Takeaways"
c_html = c_html.replace("What I Learned (The Real Talk)", "Key Takeaways")
print("1) 'The Real Talk' 수정 완료")

# 2) JSON-LD headline을 og:title(=포스트 제목)과 일치
old_headline = '"headline": "Copper Complete Guide: My Year of Experimenting With This Mineral"'
new_headline = f'"headline": "{c_title}"'
if old_headline in c_html:
    c_html = c_html.replace(old_headline, new_headline)
    print("2) JSON-LD headline 수정 완료")
else:
    print("2) JSON-LD headline — 이미 일치하거나 패턴 없음")

# 3) 잘린 FAQ 섹션 복원
# "<h3>Can You Overdose on<hr>" 부분을 찾아 완전한 FAQ로 교체
FAQ_CONTENT = """
<div class="faq-item">
<strong>Q: Can you overdose on copper?</strong>
<p>A: Yes, copper toxicity is real. The tolerable upper limit for adults is 10mg per day. I stay at 2mg, well below that. Symptoms of too much copper include nausea, vomiting, metallic taste, stomach cramps, and in severe cases liver damage. Don't exceed the recommended dose thinking more is better — it isn't.</p>
</div>

<div class="faq-item">
<strong>Q: Should I take copper and zinc at the same time?</strong>
<p>A: No. This was one of my biggest mistakes. They compete for absorption in your gut, and zinc tends to win. If you take them together, you may get very little benefit from the copper. I take copper in the morning and zinc in the afternoon. A 4–6 hour gap is enough.</p>
</div>

<div class="faq-item">
<strong>Q: How long does copper take to work?</strong>
<p>A: For me, the first noticeable change came around week 3 (less hair shedding) and the obvious improvements appeared at week 6–8. If you're expecting results in one week, you'll be disappointed and quit too early. Set a realistic timeline: 6–8 weeks minimum before you judge whether it's working.</p>
</div>

<div class="faq-item">
<strong>Q: What's the best form of copper supplement?</strong>
<p>A: Based on my testing, copper picolinate caused the fewest side effects and felt the steadiest. Copper gluconate is my second choice — gentler than citrate with good absorption. Copper citrate is cheapest and works, but I had mild stomach irritation even with food. Avoid multivitamins where copper is listed in trace amounts — that's usually not enough if you're trying to address a deficiency.</p>
</div>

<div class="faq-item">
<strong>Q: Can I get enough copper from food alone?</strong>
<p>A: Possibly, if you eat a varied diet with nuts, seeds, shellfish, organ meats, dark chocolate, and mushrooms. Many people do get adequate copper from food. I supplement because I had specific symptoms (hair loss, energy issues) that responded to supplementation. If you eat well and feel fine, food sources may be enough.</p>
</div>

<div class="faq-item">
<strong>Q: Should I cycle copper or take breaks?</strong>
<p>A: I take a 2–3 week break every couple of months, just to let my body recalibrate. This isn't backed by hard science for low-dose supplementation, but it works for me — I monitor how I feel during the break. If you're taking a therapeutic dose for a specific reason, talk to your doctor about cycling.</p>
</div>
"""

# 잘린 패턴: <h3>Can You Overdose on 으로 시작해서 <hr> (bio 앞 구분자)까지
truncated_pattern = re.compile(
    r'<h3>Can You Overdose on.*?(?=<hr\s*>?\s*<div)',
    re.DOTALL | re.IGNORECASE
)
if truncated_pattern.search(c_html):
    c_html = truncated_pattern.sub(FAQ_CONTENT + "\n", c_html, count=1)
    print("3) 잘린 FAQ 섹션 복원 완료 (6개 FAQ 항목 추가)")
else:
    # 대안: <h2 id="faq"> 이후 bio div 직전 삽입
    faq_h2 = '<h2 id="faq">Questions I Asked Myself (And Answered)</h2>'
    bio_div = '<div style="background:#f0f7ff;border-left:4px solid #4a90d9'
    if faq_h2 in c_html and bio_div in c_html:
        faq_pos = c_html.find(faq_h2) + len(faq_h2)
        bio_pos = c_html.find(bio_div, faq_pos)
        # faq_pos ~ bio_pos 사이를 FAQ로 교체 (기존 잘린 텍스트 제거)
        c_html = c_html[:faq_pos] + "\n" + FAQ_CONTENT + "\n<hr>\n" + c_html[bio_pos:]
        print("3) 대안 방식으로 FAQ 복원 완료")
    else:
        print("3) FAQ 패턴 없음 — 수동 확인 필요")

print(f"수정 후 길이: {len(c_html)}")

c_html = html_lib.unescape(c_html)
svc.posts().update(
    blogId=BLOG_ID, postId=COPPER_ID,
    body={"title": c_title, "content": c_html, "labels": c_labels},
    publish=False
).execute()
print("Copper 업데이트 완료!\n")


# ────────────────────────────────────────────────
# IRON 수정
# ────────────────────────────────────────────────
print("=== IRON 수정 중 ===")
iron = svc.posts().get(blogId=BLOG_ID, postId=IRON_ID).execute()
i_html  = iron.get("content", "")
i_title = iron.get("title", "")
i_labels = [l if isinstance(l, str) else l.get("name", "") for l in iron.get("labels", [])]

print(f"원본 길이: {len(i_html)}")

# 1) "Stockholm-based Stockholm-based" 중복 제거
before = i_html
i_html = i_html.replace("Stockholm-based Stockholm-based", "Stockholm-based")
if i_html != before:
    print("1) 'Stockholm-based' 중복 제거 완료")
else:
    print("1) 중복 없음 — 이미 수정됨")

# 2) "the the form" 오탈자 수정
before = i_html
i_html = i_html.replace("It's the the form", "It's the form")
i_html = i_html.replace("the the form", "the form")
if i_html != before:
    print("2) 'the the form' 오탈자 수정 완료")
else:
    print("2) 오탈자 없음 — 이미 수정됨")

# 3) "Real talk" 등 AI 구문 체크 & 제거
ai_phrases = {
    "Real talk:": "Here's what I found:",
    "Real Talk:": "Here's what I found:",
    "Game changer": "significant difference",
    "game changer": "significant difference",
    "bioavailable": "absorbable by the body",
    " protocol": " routine",
}
for wrong, right in ai_phrases.items():
    if wrong in i_html:
        i_html = i_html.replace(wrong, right)
        print(f"3) '{wrong}' → '{right}' 수정")

print(f"수정 후 길이: {len(i_html)}")

i_html = html_lib.unescape(i_html)
svc.posts().update(
    blogId=BLOG_ID, postId=IRON_ID,
    body={"title": i_title, "content": i_html, "labels": i_labels},
    publish=False
).execute()
print("Iron 업데이트 완료!\n")

print("=== 전체 완료 ===")
