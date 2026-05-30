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

# ── 1. Combinations 섹션의 Protein 단락 수정
#    "Protein also made a difference..." 단락 → 뒤 "What I Stopped"와 일관성 있게
OLD_PROTEIN = (
    "Protein also made a difference. I started mixing creatine with a protein shake "
    "and noticed my recovery changed. My arms felt less sore after workouts, and I "
    "could train more frequently. Maybe it's the amino acids helping repair muscle, "
    "or maybe the protein just made me eat more calories. Either way, the results "
    "were there. I didn't feel like I was wasting money anymore."
)
NEW_PROTEIN = (
    "Protein helped my recovery overall — but only when I kept it separate from creatine. "
    "Early on I tried mixing both into the same pre-workout shake. That was a mistake. "
    "My stomach wasn't happy about it. I'll get into that more below, but the short version: "
    "creatine with carbs before a workout, protein shake after. That split made a difference."
)

# ── 2. Combinations 섹션의 Caffeine 단락 수정
OLD_CAFFEINE = (
    "Caffeine was another noticeable difference. I'd always taken creatine in the morning, "
    "but I started pairing it with coffee and felt more alert. My focus during workouts "
    "changed, and I could push through tough sets. I'm not sure if the caffeine actually "
    "helped creatine absorption or just made me feel more motivated. Either way, the "
    "combination worked. I'd hit the gym with more energy and actually enjoy the sessions."
)
NEW_CAFFEINE = (
    "Coffee timing turned out to matter more than I expected. When I took creatine earlier "
    "in the morning and had coffee an hour later, my energy felt steadier throughout the day. "
    "But when I mixed them at the same time — creatine stirred into coffee, or taken back-to-back "
    "on an empty stomach — the afternoon crash hit harder. I kept experimenting with that one, "
    "and eventually landed on separating them by at least 45 minutes."
)

changes = []

if OLD_PROTEIN in c:
    c = c.replace(OLD_PROTEIN, NEW_PROTEIN)
    changes.append('Protein 단락 수정 (조합→분리)')
else:
    print('[경고] Protein 단락 원문이 정확히 매칭되지 않음 — 수동 확인 필요')

if OLD_CAFFEINE in c:
    c = c.replace(OLD_CAFFEINE, NEW_CAFFEINE)
    changes.append('Caffeine 단락 수정 (모순→타이밍 설명)')
else:
    print('[경고] Caffeine 단락 원문이 정확히 매칭되지 않음 — 수동 확인 필요')

if changes:
    result = svc.posts().patch(
        blogId=BLOG_ID, postId=POST_ID,
        body={'content': c}
    ).execute()
    print('패치 완료:')
    for ch in changes:
        print(' -', ch)
else:
    print('변경 없음')
