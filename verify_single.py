"""단일 포스트 발행후 검사"""
import sys, io, json, pickle, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
import html as _htmllib
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from post_publish_verifier import verify_and_patch

BASE_DIR = Path(__file__).parent
META_DIR = BASE_DIR / "20_Meta"
BLOG_ID  = "2812259517039331714"
POST_ID    = sys.argv[1] if len(sys.argv) > 1 else "1879354850771926594"
_arg_type  = sys.argv[2] if len(sys.argv) > 2 else ""  # 선택적 topic_type 직접 지정

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("blogger", "v3", credentials=creds)

post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
title = post.get("title", "")
html  = _htmllib.unescape(post.get("content", ""))

# topic_type 조회 (published_links.json)
topic_type = ""
try:
    pl = json.loads((META_DIR / "published_links.json").read_text(encoding="utf-8"))
    for p in pl:
        if str(p.get("post_id","")) == str(POST_ID):
            topic_type = p.get("topic_type","")
            break
except Exception:
    pass
# RAW 파일 헤더에서도 시도
if not topic_type:
    try:
        raw_dir = Path(META_DIR).parent / "pipeline" / "00_Raw"
        for f in list(raw_dir.glob("*.txt")):
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
            for l in lines:
                if l.startswith("topic_type:"):
                    topic_type = l.split(":",1)[1].strip()
                    break
    except Exception:
        pass

if _arg_type:
    topic_type = _arg_type
print(f"\n검사 대상: {title} (post_id={POST_ID}, type={topic_type or 'unknown'})\n")

result = verify_and_patch(
    svc=svc, blog_id=BLOG_ID, post_id=POST_ID,
    title=title, html=html, meta_desc="", ask_ai_fn=None, meta_dir=META_DIR,
    topic_type=topic_type
)

score = result.get("score", 0)
grade = result.get("grade", "?")
fixes = result.get("fixes", [])
lessons = result.get("lessons", [])
print(f"\n종합: {score}/10  등급: {grade}")
print(f"수정완료: {', '.join(fixes) if fixes else '없음'}")
print(f"레슨기록: {', '.join(lessons) if lessons else '없음'}")
