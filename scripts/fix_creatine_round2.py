import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pickle, re
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BLOG_ID = '2812259517039331714'
POST_ID = '5514661282768998852'

with open('token.pickle', 'rb') as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build('blogger', 'v3', credentials=creds)
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
c = post['content']

changes = []

# 1. 이미지 캡션 div 텍스트
old = c
c = c.replace(
    'Adjusting my Creatine And Complete routine for the season.',
    'My kitchen counter during week 3.'
)
if c != old: changes.append('이미지 캡션 div 수정')

# 2. H2: What Most People Get Wrong → The Mistakes I Made Early On
old = c
c = c.replace(
    'What Most People Get Wrong About This Nutrient',
    'The Mistakes I Made Early On'
)
if c != old: changes.append('H2 수정: The Mistakes I Made Early On')

# 3. H2: How It Works in the Body → Why It Took Longer Than I Expected
old = c
c = c.replace(
    'How It Works in the Body',
    'Why It Took Longer Than I Expected'
)
if c != old: changes.append('H2 수정: Why It Took Longer Than I Expected')

# 4. 과장 메타포 — "run over by a truck" 하나는 살리고 나머지 2개 완화
old = c
c = c.replace('human supercomputer', 'sharper version of myself')
if c != old: changes.append('메타포 완화: human supercomputer')

old = c
c = c.replace('swallowed a brick', 'eaten a rock')
if c != old: changes.append('메타포 완화: swallowed a brick')
# run over by a truck은 유지 (한 개는 괜찮음)

print('변경 목록:')
for ch in changes:
    print(' -', ch)
print()

if changes:
    result = svc.posts().patch(
        blogId=BLOG_ID, postId=POST_ID,
        body={'content': c}
    ).execute()
    print('패치 완료:', result['title'])
else:
    print('변경 없음')
