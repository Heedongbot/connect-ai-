"""
1. Blogger에서 Elderberry+Zinc Synergy 포스트 삭제
2. published_links.json에서 제거
3. topic_bank.json에서 Vitamin D3 Complete Guide → pending, 오늘 10:13 재스케줄
"""
import sys, io, json, pickle
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR   = Path(__file__).parent
META_DIR   = BASE_DIR / "20_Meta"
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"

ELDERBERRY_URL = "https://www.nutristacklab.com/2026/05/elderberry-and-zinc-synergy-benefits.html"

# ── 1. Blogger API 연결 ──────────────────────────────────────────────────────
try:
    import pickle as _pkl
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build as _build

    with open(TOKEN_FILE, "rb") as f:
        creds = _pkl.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    svc = _build("blogger", "v3", credentials=creds)
    print("✅ Blogger API 연결 성공")
except Exception as e:
    print(f"❌ Blogger API 연결 실패: {e}")
    sys.exit(1)

# ── 2. Elderberry 포스트 ID 찾기 ─────────────────────────────────────────────
print(f"\n🔍 포스트 검색 중: {ELDERBERRY_URL}")
post_id = None
try:
    resp = svc.posts().getByPath(blogId=BLOG_ID, path="/2026/05/elderberry-and-zinc-synergy-benefits.html").execute()
    post_id = resp.get("id")
    post_title = resp.get("title", "")
    print(f"  → 발견: [{post_id}] {post_title}")
except Exception as e:
    print(f"  → getByPath 실패: {e}")
    # fallback: list로 검색
    try:
        page_token = None
        while True:
            args = dict(blogId=BLOG_ID, maxResults=20, status="live")
            if page_token:
                args["pageToken"] = page_token
            r = svc.posts().list(**args).execute()
            for p in r.get("items", []):
                if "elderberry" in p.get("url", "").lower() and "zinc" in p.get("url", "").lower():
                    post_id = p["id"]
                    post_title = p.get("title", "")
                    print(f"  → 발견 (list): [{post_id}] {post_title}")
                    break
            if post_id:
                break
            page_token = r.get("nextPageToken")
            if not page_token:
                break
    except Exception as e2:
        print(f"  → list 검색도 실패: {e2}")

if not post_id:
    print("❌ 포스트를 찾을 수 없습니다. URL을 직접 확인해주세요.")
    sys.exit(1)

# ── 3. Blogger에서 삭제 ──────────────────────────────────────────────────────
try:
    svc.posts().delete(blogId=BLOG_ID, postId=post_id).execute()
    print(f"✅ Blogger 삭제 완료: {post_id}")
except Exception as e:
    print(f"❌ Blogger 삭제 실패: {e}")
    sys.exit(1)

# ── 4. published_links.json에서 제거 ─────────────────────────────────────────
links_path = META_DIR / "published_links.json"
links = json.loads(links_path.read_text(encoding="utf-8"))
before = len(links)
links = [l for l in links if "elderberry-and-zinc" not in l.get("url", "").lower()]
after = len(links)
links_path.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ published_links.json: {before} → {after}개 (삭제 {before - after}개)")

# ── 5. topic_bank.json: Vitamin D3 재스케줄 ──────────────────────────────────
bank_path = META_DIR / "topic_bank.json"
bank = json.loads(bank_path.read_text(encoding="utf-8"))

vitd_target = "Vitamin D3 Complete Guide"
found = False
for t in bank:
    if t.get("topic", "").lower() == vitd_target.lower():
        old_status = t.get("status")
        t["status"] = "pending"
        t["date"] = "2026-05-26"
        t["time"] = "10:13"
        if "completed_at" in t:
            del t["completed_at"]
        print(f"✅ topic_bank 업데이트: '{vitd_target}' [{old_status}] → pending (2026-05-26 10:13)")
        found = True
        break

if not found:
    print(f"⚠️ topic_bank에서 '{vitd_target}' 찾지 못함")

bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
print("✅ topic_bank.json 저장 완료")

# ── 6. Raw 파일 생성 (오케스트레이터 즉시 트리거) ──────────────────────────────
raw_dir = BASE_DIR / "00_Raw"
raw_file = raw_dir / "Vitamin_D3_Complete_Guide.md"
raw_file.write_text(f"# {vitd_target}\ntype: comprehensive_guide\n", encoding="utf-8")
print(f"✅ Raw 파일 생성: {raw_file.name}")
print(f"\n🎯 오케스트레이터가 '{vitd_target}'을 10:13에 처리합니다.")
