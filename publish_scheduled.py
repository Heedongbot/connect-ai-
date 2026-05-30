"""
publish_scheduled.py — 체크포인트에서 포스트 조립 후 지정 시간에 예약 발행

사용법:
  python publish_scheduled.py
  python publish_scheduled.py --time "2026-05-26T21:22:00+09:00"
  python publish_scheduled.py --checkpoint "[REWRITE]_Elderberry_and_Zinc_Synergy.json"
"""

import argparse, base64, json, pickle, random, re, time, requests, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
CHK_DIR    = BASE_DIR / "02_Checkpoints"
LINKS_FILE = BASE_DIR / "20_Meta" / "published_links.json"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "qwen3:14b-q4_K_M"

CSS_BLOCK = """
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      line-height: 1.65; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; background: #fafafa;
    }
    h1 { font-size: 2.2em; color: #1a1a1a; margin-bottom: 10px; line-height: 1.3; }
    h2 { font-size: 1.6em; color: #2c3e50; margin-top: 40px; margin-bottom: 20px;
         border-bottom: 2px solid #e8f1f8; padding-bottom: 10px; }
    h3 { font-size: 1.3em; color: #34495e; margin-top: 25px; margin-bottom: 15px; }
    p { margin-bottom: 16px; text-align: justify; }
    .takeaways { background: #f0f7ff; border-left: 4px solid #2a6496; padding: 16px; margin: 20px 0; border-radius: 4px; }
    .takeaways ul { margin: 10px 0; padding-left: 25px; }
    .takeaways li { margin-bottom: 8px; }
    .img-container { margin: 30px 0; text-align: center; }
    .img-container img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .img-caption { margin-top: 10px; font-size: 0.9em; color: #666; font-style: italic; padding: 12px; text-align: center; }
    blockquote { border-left: 4px solid #ddd; padding-left: 16px; margin: 20px 0; color: #666; font-style: italic; }
    hr { margin: 30px 0; border: none; border-top: 2px solid #e8e8e8; }
    a { color: #2a6496; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .disclosure { background: #f5f5f5; border: 1px solid #ddd; padding: 15px; margin-top: 40px; border-radius: 4px; font-size: 0.95em; color: #555; }
    .experience-note { background: #e8f5e9; border-left: 4px solid #4caf50; padding: 16px; margin: 20px 0; border-radius: 4px; }
"""


# ── Google OAuth
def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


# ── AI 호출 (Ollama)
def ask_ai(prompt: str, system: str = "You are an SEO expert.") -> str:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.3, "top_p": 0.9},
        }, timeout=90)
        raw = r.json().get("response", "").strip()
        line = raw.split("\n")[0].strip().strip('"*').strip()
        line = re.sub(r"^(Title|제목)[:\s]+", "", line, flags=re.IGNORECASE)
        return line
    except Exception as e:
        logging.warning(f"  AI 실패: {e}")
        return ""


# ── 실시간 Google 검색어
def get_search_keywords(nutrient: str) -> list:
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


# ── 제목 생성 (검색어 기반)
def generate_title(topic: str) -> str:
    # 영양소명 추출
    nutrient_match = re.search(r'(Vitamin [A-Z]\d?[A-Z]?|CoQ10|NMN|NAD\+?|[\w\-]+(?:\s+\w+)?)', topic)
    nutrient = nutrient_match.group(1) if nutrient_match else topic.split()[0]

    search_kws = get_search_keywords(nutrient)
    if search_kws:
        logging.info(f"  [search_kw] {len(search_kws)}개: {search_kws[:3]}")

    search_hint = ""
    if search_kws:
        search_hint = "Real Google searches for this topic:\n" + "\n".join(f"  - {s}" for s in search_kws[:8]) + "\n"

    prompt = (
        f"Task: Write ONE SEO blog post title using real search keywords.\n"
        f"Topic: {topic}\n"
        + search_hint
        + f"Requirements:\n"
        f"- Max 65 characters\n"
        f"- Must include the main nutrient name: {nutrient}\n"
        f"- Use keywords people actually search (benefits, dosage, side effects, how to take, vs, best for)\n"
        f"- Sounds informative and trustworthy\n"
        f"- No quotes, no numbering, no 'Title:' prefix\n"
        f"Output: ONLY the title text. One line."
    )
    title = ask_ai(prompt, "You are an SEO expert. Output ONLY the title text, one line.")
    if not title or len(title) < 10:
        # 폴백
        title = f"{nutrient} Benefits, Dosage, and Side Effects"
    logging.info(f"  [title] {title}")
    return title


# ── 이미지 HTML (CSS 클래스 사용 — 정상 포스트와 동일)
def img_block(url: str, alt: str, caption: str) -> str:
    clean_alt = re.sub(r'(?i)^(and|or)\s+', '', alt).strip()
    if len(clean_alt.split()) < 3:
        clean_alt = f"Health supplement routine: {clean_alt}"
    return (
        f'<div class="img-container">'
        f'<img src="{url}" alt="{clean_alt}" />'
        f'<div class="img-caption">{caption}</div></div>'
    )


# ── HTML 조립 (정상 오케스트레이터 포스트와 동일한 구조)
def assemble_html(data: dict, title: str) -> str:
    topic        = data.get("topic", "")
    hook         = data.get("hook", "")
    sections     = data.get("sections", {})
    images       = data.get("images", {})
    meta_desc    = data.get("meta_desc", f"My research notes on {topic}.")
    arch_cfg     = data.get("archetype_cfg", {})
    include_kt   = arch_cfg.get("include_kt", True)

    # topic_label
    stop = {"and","the","for","with","vs","or","of","in","a","an","synergy","guide","protocol","science"}
    words = [w.strip(':,.') for w in topic.split() if w.lower() not in stop and len(w) > 2]
    topic_label = " and ".join(words[:2]) if len(words) >= 2 else (words[0] if words else topic)
    topic_label = topic_label.title()

    # key takeaways (3개 보장)
    kt_html = ""
    if include_kt:
        kt_raw = ask_ai(
            f"Write exactly 3 Key Takeaway bullet points for a blog post about: {topic}\n"
            f"Each line: one complete sentence. No HTML. No bullets. Just 3 lines.",
            "Write concise factual bullet points. Output exactly 3 plain lines."
        )
        kt_lines = [re.sub(r'^\d+[\.\)]\s*', '', l.lstrip('-* ').strip())
                    for l in kt_raw.splitlines() if l.strip()][:3]
        if len(kt_lines) < 3:
            kt_lines = [
                f"{topic_label} has well-documented synergy effects.",
                f"Timing and dosage consistency matter for optimal results.",
                f"Pairing with complementary nutrients may enhance benefits.",
            ]
        kt_items = "".join(f"<li>{l}</li>" for l in kt_lines)
        kt_html = f'<div class="takeaways"><strong>Key Takeaways</strong><ul>{kt_items}</ul></div>'

    # hook block
    hook_clean = re.sub(r'<[^>]+>', '', hook).strip()

    # hero image
    hero_url = images.get("hero", "")
    hero_html = ""
    if hero_url:
        hero_html = img_block(hero_url, f"{topic_label} supplement testing",
                               f"My {topic_label} testing routine.")

    # sections
    sections_html = ""
    captions = [
        f"Testing {topic_label} during the first week.",
        f"Tracking {topic_label} effects over time.",
        f"Adjusting {topic_label} timing for best results.",
        f"Personal observations on {topic_label}.",
    ]
    for i, (sec_name, sec_content) in enumerate(sections.items()):
        img_key = f"s{i+1}"
        img_url = images.get(img_key, "")
        sec_img_html = ""
        if img_url:
            sec_img_html = img_block(img_url, f"{topic_label} {sec_name}", captions[i % len(captions)])
        sections_html += (
            f'<h2 id="sec{i}">{sec_name}</h2>\n'
            f'{sec_content}\n'
            f'{sec_img_html}\n'
        )

    # methodology note
    methodology = (
        '<div class="experience-note">'
        f'<strong>How I Tested This</strong>'
        f'<p style="margin:8px 0 0 0;">I tracked my own response to {topic_label} over several weeks, '
        f'adjusting timing, dosage, and combinations. '
        f'These notes reflect my personal experience and available research at the time.</p></div>'
    )

    # schema
    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": meta_desc[:150],
        "author": {"@type": "Person", "name": "NutriStack Lab"},
        "publisher": {"@type": "Organization", "name": "NutriStack Lab",
                      "logo": {"@type": "ImageObject", "url": "https://www.nutristacklab.com/favicon.ico"}},
    })

    html = f"""<script type="application/ld+json">{schema}</script>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{meta_desc[:150]}">
  <style>{CSS_BLOCK}
  </style>
</head>
<body>

{kt_html}

<hr>
<p><em>{hook_clean}</em></p>
<hr>

{hero_html}

{sections_html}

{methodology}

<div class="disclosure">
  <em>Disclosure: This post may contain affiliate links.
  Purchases made through these links support NutriStack Lab at no additional cost to you.</em>
</div>

</body>
</html>"""
    return html


# ── 체크포인트 선택
def pick_best_checkpoint() -> Path | None:
    candidates = []
    for f in sorted(CHK_DIR.glob("*.json")):
        if "test_" in f.name.lower():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("published"):
                continue
            score = sum([bool(data.get(k)) for k in ["sections", "images", "hook", "meta_desc"]])
            has_topic = bool(data.get("topic", "").strip())
            candidates.append((score + (2 if has_topic else 0), has_topic, f))
        except:
            pass
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


# ── 예약 발행
def schedule_post(title: str, html: str, labels: list, scheduled_time: str) -> dict:
    svc = get_service()
    body = {
        "title": title,
        "content": html,
        "labels": labels,
    }

    # Step 1: draft로 생성
    logging.info(f"  Draft 생성 중...")
    draft = svc.posts().insert(blogId=BLOG_ID, body=body, isDraft=True).execute()
    post_id = draft["id"]
    logging.info(f"  Draft ID: {post_id}")

    # Step 2: 예약 시간으로 publish
    logging.info(f"  예약 발행: {scheduled_time}")
    res = svc.posts().publish(
        blogId=BLOG_ID,
        postId=post_id,
        publishDate=scheduled_time
    ).execute()

    return {
        "post_id": post_id,
        "url": res.get("url", ""),
        "status": res.get("status", ""),
        "published": res.get("published", ""),
    }


def run(chk_file: str | None = None, schedule_time: str | None = None):
    # 기본 예약 시간: 오늘 21:22 KST
    if not schedule_time:
        today = datetime.now().strftime("%Y-%m-%d")
        schedule_time = f"{today}T21:22:00+09:00"

    # 체크포인트 선택
    if chk_file:
        chk_path = CHK_DIR / chk_file
    else:
        chk_path = pick_best_checkpoint()

    if not chk_path or not chk_path.exists():
        logging.error("발행 가능한 체크포인트 없음")
        return

    logging.info(f"=== 체크포인트: {chk_path.name}")
    data = json.loads(chk_path.read_text(encoding="utf-8"))
    topic = data.get("topic") or chk_path.stem.replace("_", " ").replace("[REWRITE] ", "")
    logging.info(f"  topic: {topic}")

    # 제목 생성
    logging.info("  제목 생성 중...")
    title = generate_title(topic)

    # HTML 조립
    logging.info("  HTML 조립 중...")
    html = assemble_html(data, title)
    logging.info(f"  HTML 길이: {len(html):,} chars")

    # 라벨 생성 (topic 기반 단순 생성)
    words = [w.strip(':,.') for w in topic.title().split()
             if len(w) > 2 and w.lower() not in {"and","the","for","with","vs","or","of","in","a","an"}]
    labels = list({
        "".join(words[:2]),          # e.g. "ElderberryZinc"
        "".join(words[:1]),          # e.g. "Elderberry"
        "NordicHealth",
        "NutriStackLab",
        "Supplements",
        "ImmuneHealth",
    })[:8]

    logging.info(f"  라벨: {labels}")
    logging.info(f"  예약 시간: {schedule_time}")

    # 예약 발행
    result = schedule_post(title, html, labels, schedule_time)

    logging.info(f"\n=== 예약 완료 ===")
    logging.info(f"  제목: {title}")
    logging.info(f"  post_id: {result['post_id']}")
    logging.info(f"  URL: {result['url']}")
    logging.info(f"  발행 예정: {result.get('published', schedule_time)}")

    # published_links.json 업데이트
    items = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
    items.append({
        "post_id": result["post_id"],
        "title": title,
        "topic": topic,
        "labels": labels,
        "url": result["url"],
        "date": result.get("published", schedule_time),
        "scheduled": True,
    })
    LINKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("  published_links.json 업데이트 완료")

    # 체크포인트 완료 표시
    data["published"] = True
    data["post_id"] = result["post_id"]
    data["title"] = title
    chk_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("  체크포인트 완료 표시")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--time", default=None, help="예약 시간 (ISO8601, e.g. 2026-05-26T21:22:00+09:00)")
    parser.add_argument("--checkpoint", default=None, help="체크포인트 파일명")
    args = parser.parse_args()
    run(chk_file=args.checkpoint, schedule_time=args.time)
