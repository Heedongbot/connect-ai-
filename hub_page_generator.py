"""
hub_page_generator.py — v9.0
카테고리별 허브 포스팅 생성 + Blogger 발행 + 자동 업데이트.

허브 포스트 = 해당 카테고리 전체 글을 집대성한 "입구" 포스팅.
  - 각 카테고리당 1개
  - 새 글 발행 시 자동으로 허브에 링크 추가
  - hub_posts.json에 post_id 추적

사용:
  python hub_page_generator.py --generate   # 허브 생성/업데이트
  python hub_page_generator.py --update <post_id> <title> <url>  # 새 글 추가
"""

import json, sys, io, re, pickle, html as _h, argparse, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from site_brain import SiteBrain, CATEGORY_MAP, _NUTRIENT_TO_CAT

BASE_DIR  = Path(__file__).parent
META_DIR  = BASE_DIR / "20_Meta"
HUB_FILE  = META_DIR / "hub_posts.json"
BLOG_ID   = "2812259517039331714"

# ── 카테고리별 허브 메타 ────────────────────────────────────────────
HUB_META: dict[str, dict] = {
    "minerals": {
        "title":   "Every Mineral Supplement I've Tested — My Running Notes",
        "intro":   (
            "I've spent the last two years working through the major dietary minerals "
            "one by one. This page is my running index — each entry links to the full "
            "post where I documented what actually happened. Some worked. Some surprised me. "
            "A few didn't do much at all. All honest."
        ),
        "label":   "Minerals",
    },
    "vitamins": {
        "title":   "Every Vitamin I've Tested — What I Noticed and What I Didn't",
        "intro":   (
            "Vitamins are the part of my routine I got wrong the longest. Wrong forms, "
            "wrong timing, wrong assumptions. This index collects everything I've written "
            "about vitamins — the results, the mistakes, and the occasional surprise."
        ),
        "label":   "Vitamins",
    },
    "performance": {
        "title":   "Performance Supplements I've Actually Used — Honest Notes",
        "intro":   (
            "I started testing performance supplements out of frustration with a plateau "
            "that wouldn't budge. Some moved the needle. Some did nothing. "
            "Here's the full index of what I've tried and what I learned."
        ),
        "label":   "Performance",
    },
    "sleep_stress": {
        "title":   "Sleep and Stress Supplements — What's Actually Helped Me",
        "intro":   (
            "Sleep was the last thing I thought supplements could fix. I was wrong. "
            "Here's everything I've tested in the sleep and stress category — "
            "what changed, what didn't, and what I still use."
        ),
        "label":   "Sleep",
    },
    "gut_metabolism": {
        "title":   "Gut Health and Metabolism Supplements — My Testing Log",
        "intro":   (
            "Digestion isn't glamorous to write about, but it's where I've seen some "
            "of the most consistent results. This page indexes everything I've tested "
            "in the gut health and metabolism space."
        ),
        "label":   "Gut Health",
    },
    "longevity_antioxidants": {
        "title":   "Longevity and Antioxidant Supplements — What I've Tried",
        "intro":   (
            "This is the category I approach most skeptically. A lot of longevity "
            "supplements have weak evidence and strong marketing. Here's what I've "
            "actually tested and what I concluded."
        ),
        "label":   "Longevity",
    },
    "cognitive_mood": {
        "title":   "Brain and Mood Supplements — My Honest Testing Notes",
        "intro":   (
            "Cognitive supplements are hard to evaluate objectively. "
            "I've tried to be as honest as possible about what felt real versus "
            "what might have been placebo. Here's the full index."
        ),
        "label":   "Brain & Mood",
    },
}


def get_service():
    with open(BASE_DIR / "token.pickle", "rb") as f:
        creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def load_hub_posts() -> dict:
    if HUB_FILE.exists():
        try:
            return json.loads(HUB_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_hub_posts(data: dict):
    HUB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_hub_html(category: str, posts: list) -> str:
    """허브 포스팅 HTML 생성."""
    meta    = HUB_META[category]
    title   = meta["title"]
    intro   = meta["intro"]
    cat_display = category.replace("_", " ").title()
    now_str = datetime.now().strftime("%B %Y")

    # 포스팅 항목 HTML
    entries_html = ""
    if posts:
        for p in posts:
            post_title = p.get("title", "")
            post_url   = p.get("url", "#")
            post_date  = p.get("date", "")[:7] if p.get("date") else ""
            entries_html += f"""
<div style="margin:16px 0; padding:14px 16px; background:#f9f9f9; border-left:3px solid #0066cc; border-radius:4px;">
  <h3 style="margin:0 0 6px; font-size:1.05em;">
    <a href="{post_url}" rel="noopener">{post_title}</a>
  </h3>
  <span style="font-size:0.85em; color:#888;">{post_date}</span>
</div>"""
    else:
        entries_html = "<p><em>Posts coming soon — check back shortly.</em></p>"

    html = f"""<div style="max-width:760px; margin:0 auto; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; line-height:1.7; color:#333;">

<p style="font-size:0.9em; color:#888; margin-bottom:24px;">
  Last updated: {now_str} · {len(posts)} posts
</p>

<p style="font-size:1.05em; margin-bottom:28px;">{intro}</p>

<h2 style="font-size:1.3em; border-bottom:2px solid #e2e8f0; padding-bottom:8px; margin-bottom:16px;">
  All {cat_display} Posts
</h2>

{entries_html}

<hr style="margin:40px 0; border:none; border-top:1px solid #e2e8f0;">
<p style="font-size:0.85em; color:#888;">
  This index is updated automatically as new posts are published.
  All posts reflect personal experience only — not medical advice.
  <a href="https://www.nutristacklab.com/p/4-medical-disclaimer.html">Medical Disclaimer</a>
</p>

</div>"""
    return html


def publish_hub(svc, category: str, posts: list) -> str:
    """허브 포스팅 발행 또는 업데이트. post_id 반환."""
    hubs    = load_hub_posts()
    meta    = HUB_META[category]
    title   = meta["title"]
    content = build_hub_html(category, posts)
    labels  = ["hub", meta["label"], "NutriStack"]

    existing_id = hubs.get(category, {}).get("post_id")

    if existing_id:
        # 기존 허브 업데이트
        resp = svc.posts().patch(
            blogId=BLOG_ID, postId=existing_id,
            body={"content": content, "title": title}
        ).execute()
        post_id = resp["id"]
        url     = resp.get("url", "")
        sys.stdout.write(f"  🔄 허브 업데이트: [{category}] {title[:45]}\n")
    else:
        # 신규 발행 (지수 백오프 재시도)
        from googleapiclient.errors import HttpError as _HttpError
        for _attempt in range(5):
            try:
                resp = svc.posts().insert(
                    blogId=BLOG_ID, isDraft=False,
                    body={"title": title, "content": content, "labels": labels}
                ).execute()
                break
            except _HttpError as e:
                if e.resp.status == 429:
                    wait = 15 * (2 ** _attempt)
                    sys.stdout.write(f"  ⏳ Rate limit — {wait}초 대기 후 재시도 ({_attempt+1}/5)...\n")
                    time.sleep(wait)
                else:
                    raise
        post_id = resp["id"]
        url     = resp.get("url", "")
        sys.stdout.write(f"  ✅ 허브 발행: [{category}] {title[:45]}\n")
        sys.stdout.write(f"     URL: {url}\n")
        time.sleep(5)

    # hub_posts.json 업데이트
    hubs[category] = {
        "post_id":    post_id,
        "url":        url,
        "title":      title,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "post_count": len(posts),
    }
    save_hub_posts(hubs)
    return post_id


def add_post_to_hub(svc, new_post_id: str, new_title: str, new_url: str, category: str):
    """새 글 발행 후 해당 카테고리 허브에 링크 추가."""
    hubs = load_hub_posts()
    hub_info = hubs.get(category)
    if not hub_info:
        sys.stdout.write(f"  ⚠️ 허브 없음 [{category}] — 먼저 generate 실행 필요\n")
        return

    hub_id = hub_info["post_id"]
    post   = svc.posts().get(blogId=BLOG_ID, postId=hub_id).execute()
    html   = _h.unescape(post.get("content", ""))

    # 새 항목 HTML
    new_entry = (
        f'\n<div style="margin:16px 0; padding:14px 16px; background:#f9f9f9; '
        f'border-left:3px solid #0066cc; border-radius:4px;">\n'
        f'  <h3 style="margin:0 0 6px; font-size:1.05em;">'
        f'<a href="{new_url}" rel="noopener">{new_title}</a></h3>\n'
        f'  <span style="font-size:0.85em; color:#888;">'
        f'{datetime.now().strftime("%Y-%m")}</span>\n'
        f'</div>'
    )

    # "All X Posts" 섹션 바로 뒤에 삽입
    marker = 'All '
    if marker in html:
        # h2 태그 끝 찾아서 그 뒤에 삽입
        insert_pos = html.find('</h2>', html.find(marker)) + 6
        html = html[:insert_pos] + new_entry + html[insert_pos:]
    else:
        # 폴백: <hr> 앞에 삽입
        html = html.replace('<hr style="margin:40px', new_entry + '\n<hr style="margin:40px', 1)

    # last updated + count 업데이트
    now_str    = datetime.now().strftime("%B %Y")
    post_count = html.count('<div style="margin:16px 0; padding:14px 16px; background:#f9f9f9')
    html = re.sub(
        r'Last updated: \w+ \d{4} · \d+ posts',
        f'Last updated: {now_str} · {post_count} posts',
        html
    )

    svc.posts().patch(blogId=BLOG_ID, postId=hub_id, body={"content": html}).execute()

    # hub_posts.json 카운트 업데이트
    hubs[category]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    hubs[category]["post_count"] = post_count
    save_hub_posts(hubs)
    sys.stdout.write(f"  🔗 허브 링크 추가: [{category}] ← {new_title[:45]}\n")


def generate_all_hubs():
    """전체 카테고리 허브 생성/업데이트."""
    brain  = SiteBrain()
    svc    = get_service()
    pl     = brain.published

    sys.stdout.write("허브 페이지 생성/업데이트 시작...\n\n")

    for category in HUB_META:
        # 해당 카테고리 포스팅 수집
        cat_posts = []
        for p in pl:
            title     = p.get("title", "") or p.get("topic", "")
            nutrients = p.get("nutrients", [])
            cat       = brain.categorize(title, nutrients)
            if cat == category:
                cat_posts.append({
                    "title": title,
                    "url":   p.get("url", "#"),
                    "date":  p.get("date", ""),
                })
        cat_posts.sort(key=lambda x: x.get("date",""), reverse=True)
        publish_hub(svc, category, cat_posts)

    sys.stdout.write("\n✅ 전체 허브 생성 완료\n")
    hubs = load_hub_posts()
    sys.stdout.write("\n[허브 목록]\n")
    for cat, info in hubs.items():
        sys.stdout.write(f"  {cat:<28} {info['post_count']:2}편  {info.get('url','')[:60]}\n")


# ── CLI ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="전체 허브 생성/업데이트")
    parser.add_argument("--update",   nargs=3, metavar=("POST_ID","TITLE","URL"), help="새 글 허브에 추가")
    parser.add_argument("--category", default="", help="--update 시 카테고리 지정")
    args = parser.parse_args()

    if args.generate:
        generate_all_hubs()
    elif args.update:
        post_id, title, url = args.update
        if not args.category:
            brain = SiteBrain()
            cat   = brain.categorize(title)
        else:
            cat = args.category
        svc = get_service()
        add_post_to_hub(svc, post_id, title, url, cat)
    else:
        parser.print_help()
