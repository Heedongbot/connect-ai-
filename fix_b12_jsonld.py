"""B12 포스트 JSON-LD headline/description 직접 패치"""
import pickle, re, json
from pathlib import Path
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

BLOG_ID   = "2812259517039331714"
POST_ID   = "7123665939022173318"
TOKEN_FILE = Path(__file__).parent / "token.pickle"

with open(TOKEN_FILE, "rb") as f:
    creds = pickle.load(f)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

svc  = build("blogger", "v3", credentials=creds)
post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID, fields="id,content").execute()
html = post.get("content", "")

CORRECT_HEADLINE = "What Changed When I Started Taking Vitamin B12 the Right Way"
CORRECT_DESC     = "The complete Vitamin B12 (Cobalamin) guide: how it works, best combinations, what to avoid, and my personal protocol after months of testing."

def fix_jsonld(html, headline, desc):
    def replacer(m):
        try:
            data = json.loads(m.group(1))
            if data.get("@type") == "BlogPosting":
                data["headline"] = headline
                data["description"] = desc
                return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'
        except:
            pass
        return m.group(0)
    return re.sub(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', replacer, html, flags=re.DOTALL)

new_html = fix_jsonld(html, CORRECT_HEADLINE, CORRECT_DESC)

if new_html != html:
    svc.posts().update(blogId=BLOG_ID, postId=POST_ID, body={"content": new_html}).execute()
    print("JSON-LD 패치 완료!")
    print(f"  headline: {CORRECT_HEADLINE}")
    print(f"  description: {CORRECT_DESC[:80]}...")
else:
    print("변경 없음")
