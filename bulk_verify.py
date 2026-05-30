"""
bulk_verify.py — 현재 블로그의 모든 LIVE 포스팅에 발행후 검사 일괄 실행

실행:
    python bulk_verify.py

- Blogger API로 전체 LIVE 포스트 가져옴
- 각 포스트에 verify_and_patch 호출 (rule-based 자동수정 + Blogger 패치)
- AI 스캔(ask_ai_fn) 없이 실행 → D4/A1/AI구문/이중HR/JS주석 자동수정만
- 결과 요약 출력
"""

import json
import logging
import pickle
import sys
import io
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("BulkVerify")

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
META_DIR   = BASE_DIR / "20_Meta"
BLOG_ID    = "2812259517039331714"


def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def fetch_all_live_posts(svc) -> list:
    posts = []
    page_token = None
    while True:
        kwargs = dict(blogId=BLOG_ID, status=["LIVE"], maxResults=50, orderBy="PUBLISHED")
        if page_token:
            kwargs["pageToken"] = page_token
        result = svc.posts().list(**kwargs).execute()
        batch = result.get("items", [])
        posts.extend(batch)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return posts


def main():
    from post_publish_verifier import verify_and_patch, build_discord_report

    svc = get_service()
    log.info("Blogger API 연결 완료")

    posts = fetch_all_live_posts(svc)
    log.info(f"전체 LIVE 포스트 {len(posts)}개 발견")

    summary = []

    for i, post in enumerate(posts, 1):
        post_id = post["id"]
        title   = post.get("title", "")
        html    = post.get("content", "")
        meta_desc = ""

        import re
        og_m = re.search(r'og:description.*?content="([^"]+)"', html, re.I | re.DOTALL)
        if og_m:
            meta_desc = og_m.group(1)

        log.info(f"\n[{i}/{len(posts)}] {title[:60]}")
        log.info(f"  post_id={post_id}")

        try:
            result = verify_and_patch(
                svc       = svc,
                blog_id   = BLOG_ID,
                post_id   = post_id,
                title     = title,
                html      = html,
                meta_desc = meta_desc,
                ask_ai_fn        = None,   # AI 스캔 없이 rule-based만
                ask_ai_fn_claude = None,
                meta_dir  = META_DIR,
            )

            report = build_discord_report(title, result)
            print(report)

            summary.append({
                "title":   title[:60],
                "grade":   result["grade"],
                "total":   result["total"],
                "passed":  result["passed"],
                "fixed":   [f["cat"] for f in result.get("fixed", [])],
                "rejects": result.get("instant_rejects", []),
            })

        except Exception as e:
            log.error(f"  오류: {e}")
            summary.append({
                "title":  title[:60],
                "grade":  "ERR",
                "total":  0,
                "passed": False,
                "fixed":  [],
                "rejects": [str(e)[:80]],
            })

    # 최종 요약
    print("\n" + "=" * 60)
    print(f"전체 발행후검사 완료 — {len(posts)}개 포스팅")
    print("=" * 60)
    passed = sum(1 for s in summary if s["passed"])
    print(f"통과: {passed}/{len(posts)}")
    print()
    for s in summary:
        icon = "✅" if s["passed"] else "❌"
        fixed_str = f"  수정={','.join(s['fixed'])}" if s["fixed"] else ""
        reject_str = f"  반려={s['rejects'][0][:40]}" if s["rejects"] else ""
        print(f"  {icon} [{s['grade']}] {s['total']}/10  {s['title'][:50]}{fixed_str}{reject_str}")

    # 요약 저장
    out_path = META_DIR / f"bulk_verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
