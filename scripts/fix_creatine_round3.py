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

# 1. 이미지 캡션 div — H2 제목 복붙한 어색한 텍스트
old = c
c = c.replace(
    'What changed after I stopped ignoring The Mistakes I Made Early On.',
    'The label I kept rereading before finally buying it.'
)
if c != old: changes.append('캡션 수정: The label I kept rereading...')

# 2. YMYL 위험 표현
old = c
c = c.replace(
    'creatine works for everyone',
    'creatine seems to help a lot of active people'
)
if c != old: changes.append('YMYL 수정: creatine works for everyone')

# 3. 내용 충돌 — "Creatine alone" vs 위에서 탄수화물/식사 중요하다고 설명
old = c
c = c.replace(
    'What worked? Creatine alone. No fancy combos, no gimmicks. Just a scoop in water or juice, taken consistently.',
    'What worked best for me was keeping things simple. A scoop with a meal, taken consistently, without overcomplicating it.'
)
if c != old: changes.append('내용 충돌 수정: Creatine alone → keeping things simple')

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
