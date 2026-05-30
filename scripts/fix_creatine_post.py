import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pickle, re
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BLOG_ID  = '2812259517039331714'
POST_ID  = '5514661282768998852'
NEW_TITLE = "I Tried Creatine for Six Weeks. Here's What Changed."

with open('token.pickle', 'rb') as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build('blogger', 'v3', credentials=creds)
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
c = post['content']

changes = []

# 1. H1
m = re.search(r'(<h1[^>]*>)(.*?)(</h1>)', c, re.I | re.DOTALL)
if m:
    c = c[:m.start(2)] + NEW_TITLE + c[m.end(2):]
    changes.append('H1 수정')

# 2. OG title (property="og:title" content="..." 형식)
def _replace_og_title(html):
    def repl(m):
        return m.group(1) + NEW_TITLE + m.group(3)
    return re.sub(
        r'(property=["\']og:title["\'][^>]+content=["\'])([^"\']+)(["\'])',
        repl, html, flags=re.I
    )
old = c; c = _replace_og_title(c)
if c != old: changes.append('OG title 수정')

# 3. JSON-LD headline
old = c
c = re.sub(r'("headline"\s*:\s*")([^"]+)(")', lambda m: m.group(1) + NEW_TITLE + m.group(3), c)
if c != old: changes.append('JSON-LD headline 수정')

# 4. H2 Protocol
old = c
c = c.replace('My Personal Protocol: Dose, Timing, and Form', 'What Ended Up Working For Me')
if c != old: changes.append('H2 Protocol 수정')

# 5. H2 What Actually Changed
old = c
c = c.replace('Six Weeks In: What Actually Changed', 'Six Weeks In: What I Noticed')
if c != old: changes.append('H2 What Actually Changed 수정')

# 6. 이중 HR
old = c
c = re.sub(r'(<hr\s*/>)\s*\n?\s*(<hr\s*/>)', r'\1', c, flags=re.I)
if c != old: changes.append('이중 HR 제거')

# 7. 이미지 캡션
old = c
c = c.replace(
    'A simple setup for my morning Creatine and Complete routine',
    'My kitchen counter during week 3'
)
c = re.sub(
    r'alt="creatine complete guide[^"]*"',
    'alt="The label I kept reading before finally committing"',
    c, flags=re.I
)
c = re.sub(
    r'alt=" how it works in the body"',
    'alt="Muscle saturation takes longer than I expected"',
    c, flags=re.I
)
if c != old: changes.append('이미지 캡션 수정')

# 8. 과장 메타포 완화
metaphors = [
    (r'swallowed a greasy sock', 'tasted off'),
    (r'warzone', 'rough stretch'),
    (r'battlefield', 'rough patch'),
    (r'hamster wheel', 'cycle'),
]
for pat, repl in metaphors:
    old = c
    c = re.sub(pat, repl, c, flags=re.I)
    if c != old: changes.append(f'메타포 완화: {pat}')

print('변경 목록:')
for ch in changes:
    print(' -', ch)
print()

# Blogger 패치
result = svc.posts().patch(
    blogId=BLOG_ID, postId=POST_ID,
    body={'title': NEW_TITLE, 'content': c}
).execute()
print('패치 완료:', result['title'])
