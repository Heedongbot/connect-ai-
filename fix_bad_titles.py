"""
fix_bad_titles.py — 오염된 폴백 제목 자동 수정 스크립트

대상 패턴:
  - "How I Use X Effectively: My Findings"
  - "X vs Y: My Choice After Testing"
  - "Morning vs Evening: My Choice After Testing"
  - "What Changed When I Started Taking Vitamin the Right Way"  (K2 잘림)

동작:
  1. published_links.json에서 오염 제목 탐지
  2. topic 필드로부터 AI가 올바른 제목 재생성
  3. Blogger API로 제목 패치
  4. published_links.json 로컬 업데이트
"""

import json
import re
import time
import pickle
import logging
import requests
from pathlib import Path
from datetime import datetime

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("fix_bad_titles.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

BASE_DIR            = Path(__file__).parent
TOKEN_FILE          = BASE_DIR / "token.pickle"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
SCOPES              = ["https://www.googleapis.com/auth/blogger"]
BLOG_ID             = "2812259517039331714"
LINKS_FILE          = BASE_DIR / "20_Meta" / "published_links.json"
OLLAMA_URL          = "http://localhost:11434/api/generate"
MODEL               = "qwen3:14b-q4_K_M"
DELAY               = 3   # Blogger API 속도 제한 방지 (초)

# ── 오염 제목 패턴
BAD_PATTERNS = [
    re.compile(r"^How I Use \w+ Effectively", re.IGNORECASE),
    re.compile(r"^\w+ vs \w+: My Choice After Testing$", re.IGNORECASE),
    re.compile(r"^Morning vs Evening: My Choice After Testing$", re.IGNORECASE),
    # "What Changed When I Started Taking X the Right Way" — 모든 변형 포함 (B12, Citrulline, Vitamin 등)
    re.compile(r"^What Changed When I Started Taking .+ the Right Way$", re.IGNORECASE),
]

def is_bad(title: str) -> bool:
    return any(p.search(title) for p in BAD_PATTERNS)

# ============================================================
# 제목 재생성
# ============================================================
def clean_topic(topic: str) -> str:
    t = re.sub(r"^#\s*", "", topic.strip())
    t = re.sub(r"\ntype:.*", "", t, flags=re.IGNORECASE).strip()
    return t

def ask_ai(prompt: str) -> str:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "system": "You are an SEO expert. Output ONLY the title text — one line, no extra words.",
            "stream": False,
            "options": {"temperature": 0.3, "top_p": 0.9},
        }, timeout=60)
        raw = r.json().get("response", "").strip()
        line = raw.split("\n")[0].strip().strip('"*').strip()
        line = re.sub(r"^(Title|제목)[:\s]+", "", line, flags=re.IGNORECASE)
        return line
    except Exception as e:
        logging.warning(f"AI 호출 실패: {e}")
        return ""


def get_search_keywords(nutrient: str) -> list:
    """Google Autocomplete로 실시간 검색어 수집"""
    queries = [f"{nutrient} supplement", f"{nutrient} benefits", f"{nutrient} dosage"]
    suggestions = []
    try:
        for q in queries:
            r = requests.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "chrome", "q": q, "hl": "en"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if r.status_code == 200:
                suggestions.extend(r.json()[1][:4])
            time.sleep(0.2)
        seen, out = set(), []
        for s in suggestions:
            k = s.lower().strip()
            if k not in seen:
                seen.add(k)
                out.append(s)
            if len(out) >= 10:
                break
        return out
    except Exception:
        return []


def make_title(topic: str, already_used: set) -> str:
    topic_clean = clean_topic(topic)

    # ── 영양소명 추출 (첫 번째 단어 또는 'Vitamin X' 형태)
    nutrient_match = re.search(r'(Vitamin [A-Z]\d?|CoQ10|NMN|NAD|[\w\-]+)', topic_clean)
    nutrient = nutrient_match.group(1) if nutrient_match else topic_clean.split()[0]

    # ── 실시간 Google 검색어 수집
    search_kws = get_search_keywords(nutrient)
    search_hint = ""
    if search_kws:
        search_hint = "Real Google searches:\n" + "\n".join(f"  - {s}" for s in search_kws[:8]) + "\n"
        logging.info(f"  [search_kw] {len(search_kws)}개: {search_kws[:3]}")

    # ── AI 생성
    is_guide = any(x in topic_clean.lower() for x in ["complete guide", "comprehensive guide", "ultimate guide"])
    if is_guide:
        guide_hint = (
            f"Style: '{nutrient} Benefits, Dosage, and How to Take It' or "
            f"'{nutrient} Complete Guide: Types, Dosage, and Side Effects'\n"
        )
    else:
        guide_hint = ""

    prompt = (
        f"Task: Write ONE SEO blog post title using actual search keywords.\n"
        f"Topic: {topic_clean}\n"
        + guide_hint
        + search_hint
        + f"Requirements:\n"
        f"- Max 65 characters\n"
        f"- Must include the main nutrient name (e.g. {nutrient})\n"
        f"- Use keywords people search: benefits, dosage, side effects, how to take, vs, best for\n"
        f"- Sounds informative and trustworthy\n"
        f"- Do NOT use 'What Changed When I Started Taking'\n"
        f"- No quotes, no numbering, no 'Title:' prefix\n"
        f"Output: ONLY the title. One line."
    )
    ai_title = ask_ai(prompt)

    if ai_title and 10 < len(ai_title) < 90 and ai_title not in already_used:
        return ai_title

    # ── AI 실패 시 topic_clean을 정리해서 사용
    fallback = re.sub(r"^The \w+ (Architecture|Protocol|Engine|Switch|Mechanism)[:\s]+", "", topic_clean)
    fallback = fallback.strip()[:75]
    if fallback in already_used:
        fallback = fallback[:60] + " — My Experience"
    return fallback

# ============================================================
# Blogger API
# ============================================================
def get_service():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("blogger", "v3", credentials=creds)

def patch_title(service, post_id: str, new_title: str) -> str | None:
    try:
        post = service.posts().get(blogId=BLOG_ID, postId=post_id).execute()
        body = {"title": new_title, "content": post.get("content", "")}
        # labels 보존 — 누락하면 Blogger가 labels를 삭제함
        existing_labels = post.get("labels", [])
        if existing_labels:
            body["labels"] = existing_labels
        res = service.posts().update(blogId=BLOG_ID, postId=post_id, body=body).execute()
        return res.get("url", "")
    except Exception as e:
        logging.error(f"Blogger 패치 실패 ({post_id}): {e}")
        return None

# ============================================================
# 메인
# ============================================================
def run():
    items = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
    targets = [(i, item) for i, item in enumerate(items) if is_bad(item.get("title", ""))]

    if not targets:
        logging.info("오염 제목 없음 — 완료.")
        return

    logging.info(f"오염 제목 {len(targets)}개 발견 → 수정 시작")

    service = get_service()
    already_used: set = {item.get("title", "") for item in items if not is_bad(item.get("title", ""))}
    changed = []

    for idx, (list_idx, item) in enumerate(targets):
        old_title = item["title"]
        topic     = item.get("topic", old_title)
        post_id   = item.get("post_id", "")

        logging.info(f"[{idx+1}/{len(targets)}] '{old_title}'")
        logging.info(f"  topic: {topic[:80]}")

        new_title = make_title(topic, already_used)
        already_used.add(new_title)

        logging.info(f"  → 새 제목: '{new_title}'")

        if not post_id:
            logging.warning("  post_id 없음 — 로컬만 수정")
            items[list_idx]["title"] = new_title
            items[list_idx]["title_fixed"] = True
            changed.append({"old": old_title, "new": new_title, "url": item.get("url")})
            continue

        url = patch_title(service, post_id, new_title)
        if url:
            logging.info(f"  ✅ Blogger 업데이트 성공: {url}")
            items[list_idx]["title"] = new_title
            items[list_idx]["title_fixed"] = True
            changed.append({"old": old_title, "new": new_title, "url": item.get("url")})
        else:
            logging.warning(f"  ⚠️ Blogger 업데이트 실패 — 로컬은 롤백 유지")

        if idx < len(targets) - 1:
            time.sleep(DELAY)

    # published_links.json 저장
    LINKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info(f"\n📋 수정 완료: {len(changed)}개")
    for c in changed:
        logging.info(f"  [{c['old']}] → [{c['new']}]")
        logging.info(f"    {c['url']}")

if __name__ == "__main__":
    run()
