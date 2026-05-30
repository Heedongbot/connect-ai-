"""NMN Brain-Gut 포스팅에 Erik Lindstrom 섹션 + 내부 링크 추가"""
import pickle, re
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID    = "2812259517039331714"
NMN_URL    = "https://www.nutristacklab.com/2026/05/what-changed-when-i-started-taking-nmn.html"

INTERNAL_LINKS = [
    ("NMN and Resveratrol: The Nordic Protocol",
     "https://www.nutristacklab.com/2026/04/nmn-and-resveratrol-nordic-protocol.html"),
    ("The Methylation Trap: Why Your NMN Protocol Needs a Metabolic Co-Pilot",
     "https://www.nutristacklab.com/2026/03/the-methylation-trap-why-your-nmn.html"),
    ("NMN and CoQ10 Synergy: The Nordic Stack",
     "https://www.nutristacklab.com/2026/05/nmn-and-coq10-synergy-nordic-stack.html"),
    ("Zinc and Vitamin B6 Synergy: The Nordic Protocol",
     "https://www.nutristacklab.com/2026/05/zinc-and-vitamin-b6-synergy-nordic.html"),
]

METHODOLOGY = """<hr>
<h2>About This Article</h2>
<p>This article was written by Erik Lindstrom based on a personal review of peer-reviewed literature via PubMed. All scientific claims are linked directly to their primary sources. This is intended for educational purposes only and does not constitute medical advice.</p>"""

RELATED_HTML = """<hr>
<h2>Related Posts</h2>
""" + "\n".join(
    f'<p><a href="{url}" rel="noopener">{title}</a></p>'
    for title, url in INTERNAL_LINKS
)

def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

def main():
    svc = get_service()

    # 포스트 가져오기
    path = NMN_URL.split("nutristacklab.com")[1]
    post = svc.posts().getByPath(blogId=BLOG_ID, path=path).execute()
    post_id = post["id"]
    title   = post["title"]
    html    = post.get("content", "")
    print(f"[OK] 포스트 로드: {title} (ID: {post_id})")
    print(f"     현재 길이: {len(html)} chars")

    modified = False

    # 1) Erik Lindstrom 섹션 추가
    if "Erik Lindstr" not in html:
        print("[ADD] Erik Lindstrom 섹션 주입...")
        insert = html.rfind("</body>")
        if insert == -1:
            html += METHODOLOGY
        else:
            html = html[:insert] + METHODOLOGY + html[insert:]
        modified = True
    else:
        print("[SKIP] Erik Lindstrom 이미 있음")

    # 2) 내부 링크 섹션 추가
    if "Related Posts" not in html and INTERNAL_LINKS[0][0] not in html:
        print("[ADD] 내부 링크 섹션 주입...")
        insert = html.rfind("</body>")
        if insert == -1:
            html += RELATED_HTML
        else:
            html = html[:insert] + RELATED_HTML + html[insert:]
        modified = True
    else:
        print("[SKIP] 내부 링크 이미 있음")

    if not modified:
        print("[DONE] 수정 불필요")
        return

    # Blogger 업데이트
    svc.posts().update(
        blogId=BLOG_ID,
        postId=post_id,
        body={"id": post_id, "title": title, "content": html}
    ).execute()
    print(f"[OK] Blogger 업데이트 완료: {NMN_URL}")

if __name__ == "__main__":
    main()
