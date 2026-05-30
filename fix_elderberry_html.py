"""
fix_elderberry_html.py — 예약된 Elderberry 포스트 HTML 스타일 수정
- CSS 스타일 블록 추가 (정상 오케스트레이터 포스트와 동일)
- 이미지 위치 수정 (hero → hook 이후)
- Key Takeaways 수정 (3개 bullet)
"""

import pickle, re, json, requests, time, logging
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID    = "2812259517039331714"
POST_ID    = "5651926965473076106"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "qwen3:14b-q4_K_M"

CSS_BLOCK = """
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      line-height: 1.65;
      color: #333;
      max-width: 900px;
      margin: 0 auto;
      padding: 20px;
      background: #fafafa;
    }
    h1 { font-size: 2.2em; color: #1a1a1a; margin-bottom: 10px; line-height: 1.3; }
    h2 {
      font-size: 1.6em;
      color: #2c3e50;
      margin-top: 40px;
      margin-bottom: 20px;
      border-bottom: 2px solid #e8f1f8;
      padding-bottom: 10px;
    }
    h3 { font-size: 1.3em; color: #34495e; margin-top: 25px; margin-bottom: 15px; }
    p { margin-bottom: 16px; text-align: justify; }
    .takeaways {
      background: #f0f7ff;
      border-left: 4px solid #2a6496;
      padding: 16px;
      margin: 20px 0;
      border-radius: 4px;
    }
    .takeaways ul { margin: 10px 0; padding-left: 25px; }
    .takeaways li { margin-bottom: 8px; }
    .img-container { margin: 30px 0; text-align: center; }
    .img-container img {
      max-width: 100%;
      height: auto;
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .img-caption {
      margin-top: 10px;
      font-size: 0.9em;
      color: #666;
      font-style: italic;
      padding: 12px;
      text-align: center;
    }
    blockquote {
      border-left: 4px solid #ddd;
      padding-left: 16px;
      margin: 20px 0;
      color: #666;
      font-style: italic;
    }
    hr { margin: 30px 0; border: none; border-top: 2px solid #e8e8e8; }
    .faq-item {
      margin: 20px 0;
      padding: 15px;
      background: #f9f9f9;
      border-radius: 4px;
    }
    .faq-item strong { color: #2a6496; }
    a { color: #2a6496; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .disclosure {
      background: #f5f5f5;
      border: 1px solid #ddd;
      padding: 15px;
      margin-top: 40px;
      border-radius: 4px;
      font-size: 0.95em;
      color: #555;
    }
    .experience-note {
      background: #e8f5e9;
      border-left: 4px solid #4caf50;
      padding: 16px;
      margin: 20px 0;
      border-radius: 4px;
    }
    .highlight-box {
      background: #fefce8;
      border: 1px solid #fcd34d;
      padding: 16px;
      border-radius: 4px;
      margin: 20px 0;
    }
    .comparison-table {
      width: 100%;
      border-collapse: collapse;
      margin: 20px 0;
      background: white;
      border-radius: 4px;
      overflow: hidden;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .comparison-table th {
      background: #2a6496;
      color: white;
      padding: 12px;
      text-align: left;
    }
    .comparison-table td { padding: 12px; border-bottom: 1px solid #e8e8e8; }
    .comparison-table tr:nth-child(even) { background: #f9f9f9; }
"""


def ask_ai(prompt: str) -> str:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "prompt": prompt, "stream": False,
            "system": "Output only what is requested. No extra commentary.",
            "options": {"temperature": 0.3},
        }, timeout=90)
        return r.json().get("response", "").strip()
    except Exception as e:
        logging.warning(f"AI error: {e}")
        return ""


def build_img_html(url: str, alt: str, caption: str) -> str:
    clean_alt = re.sub(r'(?i)^(and|or)\s+', '', alt).strip()
    if len(clean_alt.split()) < 3:
        clean_alt = f"Health supplement routine: {clean_alt}"
    return (
        f'<div class="img-container">'
        f'<img src="{url}" alt="{clean_alt}" />'
        f'<div class="img-caption">{caption}</div></div>'
    )


def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def run():
    svc = get_service()

    # 예약 포스트 가져오기
    result = svc.posts().list(blogId=BLOG_ID, status=["SCHEDULED"], maxResults=5).execute()
    post = None
    for p in result.get("items", []):
        if p["id"] == POST_ID:
            post = p
            break

    if not post:
        logging.error("예약 포스트를 찾을 수 없음")
        return

    logging.info(f"포스트: {post['title']}")

    # 체크포인트에서 원본 데이터 로드
    chk_path = BASE_DIR / "02_Checkpoints" / "[REWRITE]_Elderberry_and_Zinc_Synergy.json"
    data = json.loads(chk_path.read_text(encoding="utf-8"))

    topic    = data["topic"]
    hook     = data["hook"]
    sections = data["sections"]
    images   = data["images"]
    meta_desc = data.get("meta_desc", "")
    title    = post["title"]

    # Key Takeaways (3개) 재생성
    logging.info("  Key Takeaways 생성 중...")
    kt_raw = ask_ai(
        f"Write exactly 3 Key Takeaway bullet points for a blog post about: {topic}\n"
        f"Each line: one complete sentence. No HTML. No bullets. Just 3 lines."
    )
    kt_lines = [re.sub(r'^\d+[\.\)]\s*', '', l.lstrip('-* ').strip())
                for l in kt_raw.splitlines() if l.strip()][:3]
    if len(kt_lines) < 3:
        kt_lines = [
            "Elderberry and zinc together support immune function more effectively than either alone.",
            "Zinc enhances elderberry's antiviral activity by supporting immune cell signaling.",
            "Consistent daily use shows better results than taking only when symptoms appear.",
        ]
    kt_items = "".join(f"<li>{l}</li>" for l in kt_lines)

    # hook 텍스트 정리
    hook_clean = re.sub(r'<[^>]+>', '', hook).strip()

    # hero 이미지 HTML (CSS 클래스 사용)
    hero_url = images.get("hero", "")
    hero_html = ""
    if hero_url:
        hero_html = build_img_html(hero_url, f"Elderberry and zinc supplement testing", "My Elderberry and Zinc testing routine.")

    # sections + 섹션 이미지
    captions = [
        "Testing Elderberry and Zinc during the first week.",
        "Tracking effects on immunity over time.",
        "Adjusting timing for best results.",
        "Personal observations after one month.",
    ]
    sections_html = ""
    for i, (sec_name, sec_content) in enumerate(sections.items()):
        img_key = f"s{i+1}"
        img_url = images.get(img_key, "")
        sec_img = ""
        if img_url:
            sec_img = build_img_html(img_url, f"Elderberry and Zinc — {sec_name}", captions[i % len(captions)])
        sections_html += f'<h2 id="sec{i}">{sec_name}</h2>\n{sec_content}\n{sec_img}\n'

    # methodology
    methodology = (
        '<div class="experience-note">'
        '<strong>How I Tested This</strong>'
        '<p style="margin:8px 0 0 0;">I tracked my own response to elderberry and zinc over several weeks, '
        'adjusting timing, dosage, and combinations. '
        'These notes reflect personal experience and available research.</p></div>'
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

    # 전체 HTML 조립 (오케스트레이터 동일 구조)
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

<div class="takeaways">
  <strong>Key Takeaways</strong>
  <ul>{kt_items}</ul>
</div>

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

    logging.info(f"  HTML 길이: {len(html):,} chars")
    logging.info(f"  이미지 수: {len(re.findall('<img', html))}개")

    # 예약 포스트 업데이트 (발행 시간 유지)
    existing_labels = post.get("labels", [])
    body = {
        "title": title,
        "content": html,
        "labels": existing_labels,
    }
    try:
        res = svc.posts().update(
            blogId=BLOG_ID,
            postId=POST_ID,
            body=body,
            publish=False,  # 예약 상태 유지
        ).execute()
        logging.info(f"  업데이트 완료: {res.get('url','')}")
        logging.info(f"  상태: {res.get('status','')}")
        logging.info(f"  예약 시간: {res.get('published','')}")
    except Exception as e:
        logging.error(f"  업데이트 실패: {e}")


if __name__ == "__main__":
    run()
