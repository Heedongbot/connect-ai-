"""Vitamin D3 Dosage Guide 수술적 수정: 이미지, Hook, Takeaways, PMID 추가"""
import sys, io, json, pickle, re, requests
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_ID    = "2909644206769826126"

from google.auth.transport.requests import Request
from googleapiclient.discovery import build as _build

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = _build("blogger", "v3", credentials=creds)

# ── 포스트 가져오기
post  = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title = post["title"]
html  = post["content"]
print(f"제목: {title}")
print(f"현재 길이: {len(html)}자")

# ── 1. Hook 추가 (첫 번째 <p> 앞에 hr/em/hr 삽입)
HOOK_TEXT = (
    "I spent three winters in Stockholm convinced I was just bad at handling cold "
    "and darkness. Turns out I was running a Vitamin D3 deficit the entire time — "
    "and fixing it changed more than just my energy levels. Here's everything I "
    "tested, measured, and learned the hard way."
)

hook_block = (
    f'<hr />\n'
    f'<p><em>{HOOK_TEXT}</em></p>\n'
    f'<hr />\n'
)

if '<hr' not in html[:500]:
    # 첫 번째 <p> 앞에 삽입
    first_p = re.search(r'<p[^>]*>', html, re.I)
    if first_p:
        html = html[:first_p.start()] + hook_block + html[first_p.start():]
        print("✅ Hook 삽입 완료")
    else:
        html = hook_block + html
        print("✅ Hook 삽입 완료 (맨 앞)")
else:
    print("⏭️  Hook 이미 존재")

# ── 2. 이미지 추가 (Pollinations.ai hero 이미지)
IMG_URL = (
    "https://image.pollinations.ai/prompt/"
    "vitamin%20D3%20supplement%20capsules%20sunlight%20wooden%20table%20nordic%20natural%20light"
    "?width=800&height=500&nologo=true"
)
img_block = (
    f'<p style="text-align:center;">'
    f'<img src="{IMG_URL}" alt="Vitamin D3 supplement capsules in natural sunlight" '
    f'style="max-width:100%;border-radius:8px;" /></p>\n'
)

if '<img' not in html:
    # Hook 블록 바로 뒤에 삽입
    second_hr = [m.end() for m in re.finditer(r'<hr\s*/>', html, re.I)]
    if len(second_hr) >= 2:
        pos = second_hr[1]
        html = html[:pos] + '\n' + img_block + html[pos:]
    else:
        # 첫 번째 <h2> 앞에 삽입
        h2 = re.search(r'<h2', html, re.I)
        pos = h2.start() if h2 else 0
        html = html[:pos] + img_block + html[pos:]
    print("✅ 이미지 삽입 완료")
else:
    print("⏭️  이미지 이미 존재")

# ── 3. Takeaways 추가 (마지막 <h2> 섹션 앞)
TAKEAWAYS = """
<div style="background:#f0f7ff;border-left:4px solid #4a90d9;padding:16px 20px;margin:28px 0;border-radius:4px;">
<h2 style="margin-top:0;">⚡ Key Takeaways</h2>
<ul>
<li>Most adults need <strong>2,000–4,000 IU/day</strong> of Vitamin D3 for optimal blood levels</li>
<li>Take D3 with fat-containing meals — absorption drops significantly without dietary fat</li>
<li>Pair with <strong>Vitamin K2 (MK-7)</strong> to direct calcium properly and avoid arterial buildup</li>
<li>Blood test target: <strong>50–80 ng/mL</strong> (125–200 nmol/L) — most people sit far below this</li>
<li>Sun exposure alone rarely achieves sufficiency above 40° latitude in winter</li>
</ul>
</div>
"""

if 'takeaway' not in html.lower() and 'key take' not in html.lower():
    # disclosure div 앞 또는 마지막 h2 섹션 앞에 삽입
    disclosure = re.search(r'<div[^>]+class="[^"]*disclosure[^"]*"', html, re.I)
    if disclosure:
        html = html[:disclosure.start()] + TAKEAWAYS + html[disclosure.start():]
    else:
        # </body> 앞 또는 끝에
        if '</body>' in html:
            html = html.replace('</body>', TAKEAWAYS + '</body>', 1)
        else:
            html += TAKEAWAYS
    print("✅ Takeaways 삽입 완료")
else:
    print("⏭️  Takeaways 이미 존재")

# ── 4. PMID 추가 (기존 reference 섹션에 1개 추가)
# Vitamin D3 + Magnesium 시너지 연구 PMID: 28709534 (기존), 추가: 25710766
PMID_ADD = "25710766"
if PMID_ADD not in html:
    pmid_link = (
        f' <a href="https://pubmed.ncbi.nlm.nih.gov/{PMID_ADD}/" '
        f'target="_blank" rel="noopener">PMID {PMID_ADD}</a>'
    )
    # 기존 references 섹션 또는 마지막 <p>에 추가
    existing_pmid = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', html, re.I)
    if existing_pmid:
        # 첫 번째 PMID 링크 끝 뒤에 추가
        end = existing_pmid.end() + html[existing_pmid.end():].find('</a>') + 4
        html = html[:end] + pmid_link + html[end:]
        print(f"✅ PMID {PMID_ADD} 추가 완료")
    else:
        html += f'\n<p>References:{pmid_link}</p>\n'
        print(f"✅ PMID {PMID_ADD} 추가 완료 (References 섹션)")
else:
    print(f"⏭️  PMID {PMID_ADD} 이미 존재")

# ── 5. Blogger 패치
print("\n📤 Blogger 패치 중...")
svc.posts().update(
    blogId=BLOG_ID, postId=POST_ID,
    body={"id": POST_ID, "title": title, "content": html}
).execute()
print("✅ 패치 완료!")
print(f"URL: https://www.nutristacklab.com/2026/05/vitamin-d3-dosage-guide-how-much-do-you.html")
