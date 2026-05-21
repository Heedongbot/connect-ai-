"""
NutriStack Lab — Retroactive Post Updater v1.1
기존 포스팅 일괄 소급 수정 스크립트

작동 방식:
1. Blogger API로 기존 포스팅 전체 목록 조회
2. 단어수 2,000 미만 포스팅 감지
3. AI로 각 섹션 확장 (400단어로)
4. Blogger API로 업데이트 발행
5. Discord 웹훅으로 진행상황 보고
"""

import json
import re
import time
import pickle
import random
import logging
import requests
from pathlib import Path
from datetime import datetime

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('retroactive_updater.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ── 설정
BASE_DIR            = Path(__file__).parent
TOKEN_FILE          = BASE_DIR / "token.pickle"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
DISCORD_WEBHOOK_FILE= BASE_DIR / "discord_webhook.json"
SCOPES              = ['https://www.googleapis.com/auth/blogger']
BLOG_ID             = "2812259517039331714"
OLLAMA_URL          = "http://localhost:11434/api/generate"
HEAVY_MODEL         = "gemma2:9b"
LIGHT_MODEL         = "gemma2:2b"
MIN_WORDS           = 2500  # 2500단어 목표  # 이 미만이면 수정 대상
DELAY_BETWEEN_POSTS = 5     # 포스팅 간 딜레이 (초)

# ── 수정 완료 기록
DONE_FILE = BASE_DIR / "20_Meta" / "retroactive_done.json"

# ============================================================
# [1] 유틸리티
# ============================================================
def report(msg):
    """Discord 웹훅 알림"""
    try:
        if DISCORD_WEBHOOK_FILE.exists():
            data = json.loads(DISCORD_WEBHOOK_FILE.read_text(encoding='utf-8'))
            url = data.get("webhook_url", "")
            if url:
                requests.post(url, json={"content": f"🔄 **[소급수정]** {msg}"}, timeout=5)
    except:
        pass

def count_words(html):
    """HTML에서 단어수 계산"""
    text = re.sub(r'<[^>]+>', ' ', html)
    return len(text.split())

def ask_ai(prompt, system="Output only what is requested.", model=HEAVY_MODEL, timeout=300):
    """AI 호출"""
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.4, "top_p": 0.9}
        }, timeout=timeout)
        text = r.json().get('response', '').strip()
        # 프롬프트 복사 제거
        bad = ["Write ", "MINIMUM", "CRITICAL", "Rules:", "Output:"]
        lines = [l for l in text.splitlines() if not any(b in l for b in bad)]
        return "\n".join(lines).strip()
    except Exception as e:
        logging.error(f"AI 오류: {e}")
        return ""

def clean_markdown(text):
    """마크다운 제거"""
    text = re.sub(r'```[\w-]*\n?', '', text)
    text = re.sub(r'```', '', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'^\*\s+', '<li>', text, flags=re.MULTILINE)
    text = re.sub(r'^-\s+', '<li>', text, flags=re.MULTILINE)
    text = text.replace('→', '&#8594;').replace('->', '&#8594;')
    return text.strip()

def load_done():
    if DONE_FILE.exists():
        return json.loads(DONE_FILE.read_text(encoding='utf-8'))
    return []

def save_done(post_id):
    done = load_done()
    done.append({"post_id": post_id, "date": datetime.now().isoformat()})
    DONE_FILE.parent.mkdir(exist_ok=True, parents=True)
    DONE_FILE.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding='utf-8')

# ============================================================
# [2] Blogger API
# ============================================================
def get_service():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logging.info("⏳ 토큰 갱신 중...")
                creds.refresh(Request())
            except Exception as e:
                logging.warning(f"❌ 토큰 갱신 실패 (재인증 필요): {e}")
                if TOKEN_FILE.exists():
                    TOKEN_FILE.unlink()
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)
    return build('blogger', 'v3', credentials=creds)

def get_all_posts(service):
    """전체 포스팅 목록 조회"""
    posts = []
    page_token = None
    while True:
        try:
            kwargs = {"blogId": BLOG_ID, "maxResults": 20, "status": "LIVE"}
            if page_token:
                kwargs["pageToken"] = page_token
            res = service.posts().list(**kwargs).execute()
            items = res.get('items', [])
            posts.extend(items)
            page_token = res.get('nextPageToken')
            if not page_token:
                break
            time.sleep(1)
        except Exception as e:
            logging.error(f"포스팅 목록 조회 오류: {e}")
            break
    return posts

def update_post(service, post_id, title, content):
    """포스팅 업데이트"""
    try:
        body = {"title": title, "content": content}
        res = service.posts().update(
            blogId=BLOG_ID,
            postId=post_id,
            body=body
        ).execute()
        return res.get('url', '')
    except Exception as e:
        logging.error(f"업데이트 오류: {e}")
        return None

# ============================================================
# [3] 콘텐츠 확장 엔진
# ============================================================
def extract_sections(html):
    """
    기존 HTML에서 H2 섹션들 추출 (잘린 문장 방지)
    Returns: [(h2_title, section_content), ...]
    """
    sections = []
    # H2 기준으로 분리
    parts = re.split(r'(<h2[^>]*>.*?</h2>)', html, flags=re.DOTALL)

    i = 0
    while i < len(parts):
        if re.match(r'<h2[^>]*>', parts[i]):
            h2_title = re.sub(r'<[^>]+>', '', parts[i]).strip()
            content = parts[i+1] if i+1 < len(parts) else ""
            # 잘린 문장 제거: <p>로 시작하지 않는 앞부분 제거
            lines = content.splitlines()
            clean_lines = []
            started = False
            for line in lines:
                stripped = line.strip()
                if not started:
                    # <p>, <div>, <table>, <blockquote>로 시작하는 줄부터
                    if stripped.startswith(("<p>","<div","<table","<blockquote")):
                        started = True
                        clean_lines.append(line)
                else:
                    clean_lines.append(line)
            content = "\n".join(clean_lines)
            sections.append((h2_title, content))
            i += 2
        else:
            i += 1

    return sections


def expand_section(h2_title, existing_content, topic, current_words):
    """
    짧은 섹션을 400단어로 확장
    기존 내용을 유지하면서 추가 단락 생성
    """
    target_add = max(600 - current_words, 250)  # 추가할 단어수

    prompt = (
        f"You are expanding an existing blog section about: {topic}\n"
        f"Section title: {h2_title}\n\n"
        f"Existing content:\n{existing_content[:800]}\n\n"
        f"Write {target_add} additional words to expand this section.\n"
        f"Structure to follow:\n"
        f"- Paragraph 1 (100w): deeper biochemical mechanism explanation\n"
        f"- Paragraph 2 (100w): specific clinical study findings with data\n"
        f"- Paragraph 3 (100w): Nordic/Mørketid seasonal application\n"
        f"- Paragraph 4 (100w): practical protocol recommendation\n"
        f"Rules:\n"
        f"- Continue naturally from existing content\n"
        f"- Use scientific terminology with plain-language explanations in parentheses\n"
        f"- HTML <p> tags only — NO markdown, NO headers, NO bullet points\n"
        f"- Do NOT repeat what is already written\n"
        f"- Do NOT copy these instructions into output\n"
        f"Output: only the additional <p> paragraphs to append."
    )

    expansion = ask_ai(prompt,
        "You expand supplement blog content. Output additional HTML paragraphs only.",
        HEAVY_MODEL)

    if expansion:
        expansion = clean_markdown(expansion)
        return expansion
    return ""


def expand_post_content(title, html):
    """
    전체 포스팅 콘텐츠 확장
    단어수 2,000 목표
    """
    current_words = count_words(html)
    logging.info(f"  현재 단어수: {current_words}")

    if current_words >= MIN_WORDS:
        logging.info(f"  ✅ 이미 충분 ({current_words}단어) — 스킵")
        return html, False

    # 주제 추출 (제목에서)
    topic = title.strip()

    # H2 섹션 추출
    sections = extract_sections(html)
    logging.info(f"  섹션 수: {len(sections)}개")

    if not sections:
        logging.warning(f"  ⚠️ 섹션 없음 — 전체 확장 시도")
        # 전체 본문 확장
        expansion = ask_ai(
            f"Expand this blog post about {topic} by adding 1,500 more words.\n"
            f"Add 3 new sections with <h2> headers.\n"
            f"Each section minimum 500 words. HTML only. No markdown.\n"
            f"Topics:\n"
            f"1. Deep biochemical mechanism (enzyme pathways, receptor interactions)\n"
            f"2. Clinical trial evidence (specific studies, dosage data)\n"
            f"3. Nordic winter application protocol (timing, stacking, seasonal tips)\n"
            f"Use <p> tags. Include scientific terms with plain explanations.",
            "You expand supplement blog content. HTML only. No markdown.",
            HEAVY_MODEL
        )
        if expansion:
            # Disclaimer 앞에 삽입
            disclaimer_pos = html.find('<p style="font-size:0.85em')
            if disclaimer_pos > 0:
                html = html[:disclaimer_pos] + clean_markdown(expansion) + "\n" + html[disclaimer_pos:]
            else:
                html = html + clean_markdown(expansion)
        return html, True

    # 각 섹션 확장
    new_html = html
    for h2_title, content in sections:
        sec_words = count_words(content)
        logging.info(f"    섹션 '{h2_title[:40]}': {sec_words}단어")

        if sec_words < 500:  # 500단어 미만 섹션 확장
            expansion = expand_section(h2_title, content, topic, sec_words)
            if expansion:
                # 해당 섹션 내용 뒤에 삽입
                # 다음 H2 또는 <hr> 앞에 삽입
                search = content.rstrip()
                if search in new_html:
                    new_html = new_html.replace(
                        search,
                        search + "\n" + expansion
                    )
                    new_words = count_words(new_html)
                    logging.info(f"      → 확장 후: {new_words}단어")

        # 목표 달성 시 중단
        if count_words(new_html) >= MIN_WORDS:
            break

    final_words = count_words(new_html)
    logging.info(f"  최종 단어수: {final_words}")
    return new_html, True


# ============================================================
# [4] 메인 소급 수정
# ============================================================
def run_retroactive():
    """전체 소급 수정 실행"""
    logging.info("🔄 NutriStack 소급 수정 시작")
    report("소급 수정 스크립트 시작")

    service = get_service()
    if not service:
        logging.error("❌ Blogger 서비스 초기화 실패")
        return

    # 전체 포스팅 조회
    logging.info("📋 포스팅 목록 조회 중...")
    posts = get_all_posts(service)
    logging.info(f"  총 {len(posts)}개 포스팅 발견")

    # 완료된 포스팅 제외
    done_ids = {d["post_id"] for d in load_done()}

    # 수정 대상 필터링
    targets = []
    for post in posts:
        post_id = post.get('id', '')
        if post_id in done_ids:
            continue
        content = post.get('content', '')
        words = count_words(content)
        if words < MIN_WORDS:
            targets.append({
                "id": post_id,
                "title": post.get('title', ''),
                "url": post.get('url', ''),
                "content": content,
                "words": words
            })

    logging.info(f"\n  📊 수정 대상: {len(targets)}개 포스팅")
    logging.info(f"  기준: {MIN_WORDS}단어 미만")
    report(f"수정 대상 {len(targets)}개 발견 (기준: {MIN_WORDS}단어 미만)")

    if not targets:
        logging.info("  ✅ 모든 포스팅이 기준 충족 — 종료")
        return

    # 수정 실행
    success = 0
    failed = 0

    for i, post in enumerate(targets, 1):
        logging.info(f"\n{'='*50}")
        logging.info(f"[{i}/{len(targets)}] {post['title'][:50]}")
        logging.info(f"  현재: {post['words']}단어 | URL: {post['url'][:60]}")
        report(f"[{i}/{len(targets)}] 수정 중: {post['title'][:40]}")

        try:
            # 콘텐츠 확장
            new_content, changed = expand_post_content(
                post['title'], post['content']
            )

            if not changed:
                save_done(post['id'])
                continue

            # 최종 단어수 확인
            final_words = count_words(new_content)
            logging.info(f"  📝 확장 완료: {post['words']} → {final_words}단어")

            # Blogger 업데이트
            url = update_post(service, post['id'], post['title'], new_content)
            if url:
                logging.info(f"  ✅ 업데이트 완료")
                report(f"✅ 수정 완료: {post['title'][:40]} ({final_words}단어)")
                save_done(post['id'])
                success += 1
            else:
                logging.error(f"  ❌ 업데이트 실패")
                failed += 1

        except Exception as e:
            logging.error(f"  ❌ 오류: {e}")
            failed += 1

        # 딜레이 (API Rate Limit 방지)
        if i < len(targets):
            logging.info(f"  ⏳ {DELAY_BETWEEN_POSTS}초 대기...")
            time.sleep(DELAY_BETWEEN_POSTS)

    # 최종 보고
    logging.info(f"\n{'='*50}")
    logging.info(f"🏆 소급 수정 완료!")
    logging.info(f"  ✅ 성공: {success}개")
    logging.info(f"  ❌ 실패: {failed}개")
    logging.info(f"  ⏭️ 스킵: {len(targets)-success-failed}개")
    report(f"🏆 소급 수정 완료! 성공:{success} 실패:{failed}")


# ============================================================
# [5] 실행
# ============================================================
if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args:
        # 전체 실행
        run_retroactive()

    elif args[0] == "scan":
        # 수정 대상만 스캔 (실제 수정 안 함)
        service = get_service()
        posts = get_all_posts(service)
        done_ids = {d["post_id"] for d in load_done()}
        logging.info(f"\n📋 전체 포스팅 단어수 스캔:")
        targets = 0
        for post in posts:
            if post.get('id') in done_ids:
                continue
            words = count_words(post.get('content', ''))
            status = "🔴 수정필요" if words < MIN_WORDS else "✅ 충족"
            logging.info(f"  {status} [{words:,}단어] {post.get('title','')[:50]}")
            if words < MIN_WORDS:
                targets += 1
        logging.info(f"\n총 수정 대상: {targets}개")

    elif args[0] == "one":
        # 포스팅 1개만 테스트 수정
        service = get_service()
        posts = get_all_posts(service)
        done_ids = {d["post_id"] for d in load_done()}
        for post in posts:
            if post.get('id') in done_ids:
                continue
            words = count_words(post.get('content', ''))
            if words < MIN_WORDS:
                logging.info(f"테스트: {post['title'][:50]} ({words}단어)")
                new_content, changed = expand_post_content(post['title'], post['content'])
                if changed:
                    url = update_post(service, post['id'], post['title'], new_content)
                    logging.info(f"완료: {url}")
                    save_done(post['id'])
                break

    else:
        print("""
사용법:
  python retroactive_updater.py          # 전체 실행
  python retroactive_updater.py scan     # 수정 대상 스캔만
  python retroactive_updater.py one      # 1개만 테스트
        """)