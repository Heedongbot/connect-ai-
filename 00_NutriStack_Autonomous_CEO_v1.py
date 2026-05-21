"""
NutriStack Lab — Autonomous CEO v1.0
=======================================
24/7 Self-Improving Business Engine
- Scans published posts for quality (Auditor)
- Triggers autonomous rewrites/restores
- Monitors business health & bottlenecks
"""

import os
import json
import time
import random
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
import requests

# 기본 경로 설정
BASE_DIR = Path(__file__).parent
META_DIR = BASE_DIR / "20_Meta"
RAW_DIR  = BASE_DIR / "00_Raw"
PROMPT_DIR = BASE_DIR / "06_prompts"
LOG_FILE = BASE_DIR / "autonomous_ceo.log"

# 설정 로드
try:
    with open(BASE_DIR / ".env", "r") as f:
        env = dict(line.strip().split("=", 1) for line in f if "=" in line)
except: env = {}

OLLAMA_URL = "http://localhost:11434/api/generate"
HEAVY_MODEL = "qwen3:14b-q4_K_M"   # 실제 설치된 최신 Qwen3 모델명
LIGHT_MODEL = "qwen2:7b-instruct-q4_0"          # 실제 설치된 모델명

import socket, sys
_instance_socket = None
def ensure_single_instance(port):
    global _instance_socket
    try:
        _instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _instance_socket.bind(('127.0.0.1', port))
    except socket.error:
        print(f"\n\u26a0\ufe0f [중복 실행 방지] 이미 동일한 프로그램이 실행 중입니다 (포트 {port} 점유 중).")
        print("중복 실행을 방지하기 위해 이 인스턴스를 즉시 종료합니다.\n")
        sys.exit(0)

ensure_single_instance(19998)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)

# ============================================================
# 유틸리티
# ============================================================
def report_to_discord(agent, message):
    """Discord 웹훅으로 메시지 전송. 1900자 초과 시 자동 분할."""
    webhook_path = BASE_DIR / "discord_webhook.json"
    if not webhook_path.exists(): return
    try:
        cfg = json.loads(webhook_path.read_text())
        url = cfg.get("webhook_url")
        if not url: return
        
        header  = f"[{agent}] "
        max_len = 1900 - len(header)
        
        # 1900자 이내면 한 메시지로
        if len(message) <= max_len:
            requests.post(url, json={"content": f"{header}{message}"}, timeout=5)
        else:
            # 줄 단위로 저직엄 분할
            lines   = message.splitlines(keepends=True)
            chunk   = ""
            is_first = True
            for line in lines:
                if len(chunk) + len(line) > max_len:
                    prefix = header if is_first else "[...] "
                    requests.post(url, json={"content": f"{prefix}{chunk.strip()}"}, timeout=5)
                    chunk    = line
                    is_first = False
                else:
                    chunk += line
            if chunk.strip():
                prefix = header if is_first else "[...] "
                requests.post(url, json={"content": f"{prefix}{chunk.strip()}"}, timeout=5)
    except: pass

def load_agent(filename):
    path = PROMPT_DIR / filename
    return path.read_text(encoding='utf-8') if path.exists() else ""

def load_lessons():
    lessons_file = META_DIR / "agent_lessons.json"
    if lessons_file.exists():
        try: return json.loads(lessons_file.read_text(encoding='utf-8'))
        except: return {}
    return {}

def load_agent_with_lessons(filename):
    base_prompt = load_agent(filename)
    agent_key = filename.replace(".md", "")
    lessons = load_lessons()
    agent_lessons = lessons.get(agent_key, [])
    if not agent_lessons: return base_prompt
    
    recent = agent_lessons[-15:]
    lessons_block = "\n\n## ⚠️ CRITICAL LESSONS FROM PAST AUDITS/REJECTIONS (MUST FOLLOW):\n"
    for i, l in enumerate(recent, 1):
        lessons_block += f"{i}. [{l.get('date','?')}] {l.get('lesson','')}\n"
    
    logging.info(f"  🧠 [{agent_key}] 과거 레슨 {len(recent)}개 주입")
    return base_prompt + lessons_block

def ask_ai(prompt, system_prompt="", model=LIGHT_MODEL, timeout=600):
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "num_predict": 2048, 
                "temperature": 0.7,
                "num_ctx": 8192,  # 긴 글을 소화하기 위해 컨텍스트 윈도우 확장
                "repeat_penalty": 1.2,
                "repeat_last_n": 64
            }
        }
        res = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        
        if res.status_code != 200:
            logging.error(f"  ❌ Ollama 서버 오류 (HTTP {res.status_code}): {res.text}")
            return ""
            
        return res.json().get("response", "").strip()
    except Exception as e:
        logging.error(f"  ❌ AI 통신 예외 발생: {e}")
        return ""

import pickle
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BLOG_ID      = "2812259517039331714"
CLIENT_SECRETS = BASE_DIR / "client_secrets.json"
TOKEN_FILE   = BASE_DIR / "token.pickle"
SCOPES       = ['https://www.googleapis.com/auth/blogger',
                 'https://www.googleapis.com/auth/drive.file']

def clean_html_for_audit(html):
    """
    LLM 분석을 위해 HTML에서 쓸데없이 길고 무거운 요소들을 걷어내고
    의미 있는 HTML 태그(TOC, CSS, JSON-LD, FAQ 등)만 온전히 남겨둡니다.
    """
    import re
    # 1. base64 이미지 인라인 링크 축소 (엄청난 토큰 낭비 차단)
    html_cleaned = re.sub(r'src="data:image/[^;]+;base64,[^"]+"', 'src="data:image/png;base64,[BASE64_IMAGE_DATA_TRUNCATED]"', html)
    
    # 2. 아주 무거운 style 태그나 SVG 등 불필요한 바이너리/미디어 데이터 축소
    html_cleaned = re.sub(r'<svg.*?</svg>', '[SVG_ICON_TRUNCATED]', html_cleaned, flags=re.DOTALL)
    
    # 3. script 태그 중 JSON-LD(ld+json)만 남기고 일반 자바스크립트는 제거 (토큰 최적화)
    def script_repl(match):
        script_content = match.group(0)
        if 'application/ld+json' in script_content:
            return script_content # JSON-LD는 보존!
        return '[JS_SCRIPT_TRUNCATED]'
        
    html_cleaned = re.sub(r'<script.*?</script>', script_repl, html_cleaned, flags=re.DOTALL)
    
    # 4. 무거운 외부 스타일 시트나 장황한 CSS 스타일 태그 제거
    # (인라인 스타일 style="..."은 보존하여 CSS 점수 평가 가능케 함!)
    html_cleaned = re.sub(r'<style.*?</style>', '[STYLE_TAG_TRUNCATED]', html_cleaned, flags=re.DOTALL)
    
    # 5. 공백 정리
    html_cleaned = re.sub(r'\s+', ' ', html_cleaned).strip()
    return html_cleaned

def get_blogger_service():
    """Blogger API 서비스 인스턴스 반환"""
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                return None
        else:
            return None
    return build('blogger', 'v3', credentials=creds)

# ============================================================
# 자율 감사 루프 (Audit & Self-Healing)
# ============================================================
def run_audit_cycle():
    """무작위 과거 포스팅 3개 감사 및 수정 지시 (GPU 부하 방지 로직 포함)"""
    # 1. GPU 점유 확인 (Orchestrator가 일하고 있는지 체크)
    cp_dir = BASE_DIR / "02_Checkpoints"
    all_cps = list(cp_dir.glob("*.json"))
    active_cps = []
    for cp in all_cps:
        try:
            if (datetime.now() - datetime.fromtimestamp(cp.stat().st_mtime)).total_seconds() < 600:
                active_cps.append(cp)
        except: pass

    if active_cps:
        logging.info("  💤 Orchestrator가 작업 중입니다. 10분 뒤에 다시 확인합니다.")
        return False, 10

    # 2. 휴식 시간 확인 (최근 포스팅 후 40분간 휴식)
    links_file = META_DIR / "published_links.json"
    if links_file.exists():
        last_mod = datetime.fromtimestamp(links_file.stat().st_mtime)
        wait_until = last_mod + timedelta(minutes=40)
        now = datetime.now()
        if now < wait_until:
            wait_min = int((wait_until - now).total_seconds() / 60) + 1
            logging.info(f"  ❄️ GPU 쿨링 중... {wait_min}분 뒤에 감사를 다시 시도합니다.")
            return False, wait_min

    # 3. 작업 시작
    if not links_file.exists(): return False, 60

    try:
        links = json.loads(links_file.read_text(encoding='utf-8'))
        if not links: return False, 60
        
        # ── [개선] 감사 중복 대상 제외 필터링 (품질 양호/승인 대기 글 제외)
        excluded_urls = set()
        
        # 1) pending_approval.json 대기 중이거나 진행 중인 글 제외
        pending_file = META_DIR / "pending_approval.json"
        if pending_file.exists():
            try:
                p_data = json.loads(pending_file.read_text(encoding='utf-8'))
                for p in p_data:
                    if p.get("status") in ["waiting", "approved", "done"]:
                        excluded_urls.add(p.get("url"))
            except: pass
            
        # 2) performance_db.json에서 최근 30일 이내에 KEEP으로 통과했거나 이미 done인 글 제외
        perf_file = META_DIR / "performance_db.json"
        if perf_file.exists():
            try:
                perf_data = json.loads(perf_file.read_text(encoding='utf-8'))
                thirty_days_ago = datetime.now() - timedelta(days=30)
                for rec in perf_data:
                    if rec.get("source") == "CEO_Auditor":
                        audited_at_str = rec.get("audited_at")
                        if audited_at_str:
                            audited_at = datetime.strptime(audited_at_str, "%Y-%m-%d %H:%M:%S")
                            if audited_at > thirty_days_ago:
                                if rec.get("status") in ["KEEP", "done"]:
                                    excluded_urls.add(rec.get("url"))
            except: pass

        # 필터 대상 적용
        candidates = [l for l in links if l.get("url") not in excluded_urls]
        if not candidates:
            logging.info("  🎉 모든 포스팅이 최근 30일 이내에 감사를 완료했습니다! 대상 풀을 전체로 리셋합니다.")
            candidates = links
            
        # ── [개선] 한번에 3개 무작위 선택하여 감사 순회 (3시간에 3개씩 하루 8회 = 24개)
        targets = random.sample(candidates, min(3, len(candidates)))
        logging.info(f"🔍 과거 글 감사 순회 시작 (대상 {len(targets)}개 선택)")

        for idx, target in enumerate(targets, 1):
            title = target.get("title")
            url = target.get("url")
            topic = target.get("topic", title)

            logging.info(f"🔍 [{idx}/{len(targets)}] 감사 시작: {title}")
            
            # Blogger API로 기사 본문만 직접 가져오기 (네비/푸터 잡음 제거)
            post_id   = target.get("post_id", None)
            post_html = ""
            
            if post_id:
                try:
                    svc = get_blogger_service()
                    if svc:
                        post_data = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
                        post_html = post_data.get("content", "")
                        logging.info(f"  [API] 기사 본문 수집 완료 ({len(post_html)}자)")
                except Exception as e:
                    logging.warning(f"  API 조회 실패, URL 폴백: {e}")

            if not post_html:
                try:
                    svc = get_blogger_service()
                    if svc and url:
                        path = url.replace("https://www.nutristacklab.com", "")
                        post_data = svc.posts().getByPath(blogId=BLOG_ID, path=path).execute()
                        post_html = post_data.get("content", "")
                        post_id   = post_data.get("id")
                        logging.info(f"  [API/Path] 기사 본문 수집 완료 ({len(post_html)}자)")
                except Exception as e:
                    logging.warning(f"  getByPath 실패, HTTP 폴백: {e}")

            if not post_html:
                logging.info(f"  [HTTP 폴백] URL 크롤링: {url}")
                res = requests.get(url, timeout=15)
                content = res.text if res.status_code == 200 else ""
                if not content:
                    logging.warning(f"  본문 수집 실패: {url} (HTTP {res.status_code})")
                    continue
                post_html = content

            # HTML 정제 (의미 있는 HTML 태그, JSON-LD, TOC 등 보존)
            text_content = clean_html_for_audit(post_html)

            logging.info(f"  AI 분석 요청 중... (기사 본문 {len(text_content)}자)")
            auditor_sys = load_agent_with_lessons("11_CEO_Auditor.md")
            
            full_prompt = (
                f"제목: {title}\n"
                f"주제: {topic}\n"
                f"URL: {url}\n\n"
                f"[기사 본문]\n{text_content[:30000]}\n\n"
                f"위 기사 본문만을 분석하라."
            )
            
            report = ask_ai(full_prompt, auditor_sys, HEAVY_MODEL, timeout=600)

            if not report: 
                logging.warning("  AI 응답이 비어있거나 통신에 실패했습니다.")
                continue

            # 결과 파싱
            score_match = re.search(r'SCORE:\s*([\d.]+)', report)
            status_match = re.search(r'STATUS:\s*(\w+)', report)
            
            score = float(score_match.group(1)) if score_match else 5.0
            status = status_match.group(1) if status_match else "KEEP"

            # ── [프로그램 기반 추가 엄격 필터링]
            override_reasons = []
            
            calculated_words = len(text_content.split())
            if calculated_words < 1000:
                override_reasons.append(f"단어 수 1000 미만 ({calculated_words}단어)")
                
            title_lower = title.lower()
            polluted_keywords = ["stopped", "common", "comparing", "taking", "vs and"]
            for pk in polluted_keywords:
                if re.search(r'\b' + re.escape(pk) + r'\b', title_lower):
                    override_reasons.append(f"제목 오염 키워드 검출 ('{pk}')")
            
            text_lower = text_content.lower()
            virtual_patterns = [
                "nordic journal of", "journal of nordic",
                "tromsø 연구", "tromso 연구", "tromsø study", "tromso study"
            ]
            for vp in virtual_patterns:
                if vp in text_lower:
                    override_reasons.append(f"가상 저널/연구 인용 의심 검출 ('{vp}')")
                    
            if re.search(r'(?:background|color|border)[^:;]*:\s*[a-fA-F0-9]{6}\b', post_html):
                override_reasons.append("CSS 컬러 코드 내 # 누락 검출")
                
            if re.search(r'href=["\']sec\d+["\']', post_html):
                override_reasons.append("목차(TOC) 내부 anchor 링크 # 누락 검출 (href='sec0')")
                
            if "→" in post_html or "&8594;" in post_html:
                override_reasons.append("화살표 엔티티 오염 검출 (→ 또는 &8594; 사용됨, &#8594; 권장)")
                
            if "drive.google.com/thumbnail" in post_html:
                override_reasons.append("구버전 Google Drive 이미지 링크 검출")

            pmids = re.findall(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', post_html)
            for pmid in pmids:
                if int(pmid) > 44000000:
                    override_reasons.append(f"가상 PMID 의심 번호 검출 ({pmid} > 44,000,000)")

            h2_sections = re.findall(r'<h2[^>]*>.*?</h2>(.*?)(?=<h2|<hr|$)', post_html, re.DOTALL)
            for sec in h2_sections:
                text = re.sub(r'<[^>]+>', ' ', sec).strip()
                if len(text.split()) < 30:
                    override_reasons.append("빈 섹션 감지 (텍스트 30단어 미만)")

            if override_reasons:
                original_score = score
                score = min(score, 5.9)
                status = "REWRITE"
                report = re.sub(r'SCORE:\s*[\d.]+/10', f'SCORE: {score}/10 (AI 원평가: {original_score}/10 - 프로그램 강제 강등 🚨)', report)
                report += f"\n\n[프로그램 엄격 규칙 위반 적발]:\n" + "\n".join(f"- {r}" for r in override_reasons)

            logging.info(f"  📊 감사 결과: {score}/10 -> {status}")

            if status in ["REWRITE", "RESTORE_IMAGE"]:
                reason = report.split("\n", 2)[-1].strip()
                orig_date = target.get("date", "날짜 정보 없음")
                
                post_id = target.get("post_id", None)
                if not post_id:
                    try:
                        svc = get_blogger_service()
                        if svc:
                            res_search = svc.posts().getByPath(blogId=BLOG_ID, path=url.replace("https://www.nutristacklab.com", "")).execute()
                            post_id = res_search.get("id")
                    except Exception as e:
                        logging.warning(f"  post_id 조회 실패 (인터넷 감사에서 직접 검색): {e}")

                pending_file = META_DIR / "pending_approval.json"
                pending_data = []
                if pending_file.exists():
                    try:
                        pending_data = json.loads(pending_file.read_text(encoding='utf-8'))
                    except:
                        pending_data = []
                
                if not any(p.get("topic") == topic and p.get("status") == "waiting" for p in pending_data):
                    pending_data.append({
                        "topic": topic,
                        "title": title,
                        "status": "waiting",
                        "type": status,
                        "action": "UPDATE",
                        "original_date": orig_date,
                        "url": url,
                        "post_id": post_id,
                        "before_score": score,
                        "critic_feedback": f"[자율감사 {status}] 종합 점수: {score}/10. 사유: {reason}"
                    })
                    pending_file.write_text(json.dumps(pending_data, ensure_ascii=False, indent=2), encoding='utf-8')
                
                seo = re.search(r'SEO:\s*([\d.]+)', report)
                human = re.search(r'인간\s*느낌:\s*([\d.]+)', report)
                footprint = re.search(r'AI\s*footprint:\s*([\d.]+)', report)
                safety = re.search(r'건강\s*(?:블로그\s*)?안전성\s*:\s*([\d.]+)', report)
                adsense = re.search(r'애드센스\s*(?:친화성)?\s*:\s*([\d.]+)', report)
                
                seo_val       = seo.group(1) if seo else '?'
                human_val     = human.group(1) if human else '?'
                footprint_val = footprint.group(1) if footprint else '?'
                safety_val    = safety.group(1) if safety else '?'
                adsense_val   = adsense.group(1) if adsense else '?'

                reason_lines = [l.strip() for l in report.splitlines() if l.strip() and not l.strip().startswith("SCORE:") and not l.strip().startswith("STATUS:")]
                reason_full  = "\n".join(reason_lines)

                status_korean = {
                    "REWRITE": "⚠️ 수정 및 리라이트 대상",
                    "RESTORE_IMAGE": "🖼️ 이미지 복원 대상",
                    "KEEP": "✅ 감사 통과 (유지)"
                }.get(status, status)

                override_warning = ""
                if override_reasons:
                    override_warning = (
                        f"🚨 **[프로그램 규칙 위반 강제 강등]**\n"
                        f"원래 AI 평점 평균은 **{original_score}/10**이었으나, 아래 규칙 위반으로 인해 최종 점수가 **5.9점**으로 강제 조정되었습니다:\n"
                        + "\n".join(f"- ❌ {r}" for r in override_reasons)
                        + "\n\n"
                    )

                ai_avg = original_score if override_reasons else score
                msg1 = (
                    f"\U0001f6a8 **[자율감사 업데이트 필요]**\n"
                    f"\U0001f4cc **대상**: {title}\n"
                    f"\U0001f4c5 **원본 발행일**: {orig_date}\n"
                    f"\U0001f517 {url}\n"
                    f"\U0001f4ca **최종 보정 점수**: **{score}/10** | 조치: **{status_korean}**\n"
                    f"📊 **AI 순수 평가 평균**: **{ai_avg}/10** (아래 개별 점수의 수학적 평균)\n\n"
                    f"{override_warning}"
                    f"\U0001f4c8 **항목별 점수**\n"
                    f"| 항목 | 점수 |\n"
                    f"| --- | --- |\n"
                    f"| SEO | {seo_val}/10 |\n"
                    f"| 인간 느낌 | {human_val}/10 |\n"
                    f"| AI footprint | {footprint_val}/10 |\n"
                    f"| 건강 안전성 | {safety_val}/10 |\n"
                    f"| 애드센스 | {adsense_val}/10 |"
                )
                report_to_discord("CEO_Auditor", msg1)

                if reason_full:
                    report_to_discord("CEO_Auditor_Detail", f"\U0001f4dd **항목별 사유 (한국어)**:\n{reason_full}")

                msg3 = (
                    f"\u2705 승인하려면 디스코드에서:\n"
                    f"`!\uc2b9인 {topic[:30]}`\n\n"
                    f"\u274c 폐기하려면:\n"
                    f"`!\ud3d0기 {topic[:30]}`"
                )
                report_to_discord("CEO_Action", msg3)
            else:
                logging.info(f"  ✅ 품질 양호 (KEEP)")

            seo = re.search(r'SEO:\s*([\d.]+)', report)
            human = re.search(r'인간\s*느낌:\s*([\d.]+)', report)
            footprint = re.search(r'AI\s*footprint:\s*([\d.]+)', report)
            safety = re.search(r'건강\s*(?:블로그\s*)?안전성\s*:\s*([\d.]+)', report)
            adsense = re.search(r'애드센스\s*(?:친화성)?\s*:\s*([\d.]+)', report)

            audit_record = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "audited_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "CEO_Auditor",
                "title": title,
                "url": url,
                "scores": {
                    "seo":         float(seo.group(1)) if seo else None,
                    "humanity":    float(human.group(1)) if human else None,
                    "ai_footprint":float(footprint.group(1)) if footprint else None,
                    "health_safety":float(safety.group(1)) if safety else None,
                    "adsense":     float(adsense.group(1)) if adsense else None,
                    "total":       score,
                },
                "status": status,
            }

            perf_file = META_DIR / "performance_db.json"
            try:
                db = json.loads(perf_file.read_text(encoding='utf-8')) if perf_file.exists() else []
                db.append(audit_record)
                db = db[-500:]
                perf_file.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
                logging.info(f"  💾 RL 데이터 저장 완료 → performance_db.json ({len(db)}건 누적)")
            except Exception as e:
                logging.warning(f"  ⚠️ RL 데이터 저장 실패: {e}")

            # GPU 부하 및 디스코드 스팸 방지를 위해 순회 사이 간격 추가
            if idx < len(targets):
                logging.info("  ❄️ 다음 감사 전 GPU 쿨링 (20초 대기)...")
                time.sleep(20)

        # ── [자동 복구 시스템 (Self-Healing)] ── (사용자 요청으로 자동 승인 및 리라이트 기능 보류)
        # try:
        #     pending_file = META_DIR / "pending_approval.json"
        #     if pending_file.exists():
        #         p_data = json.loads(pending_file.read_text(encoding='utf-8'))
        #         waiting_items = [item for item in p_data if item.get("status") == "waiting" and item.get("type") == "REWRITE"]
        #         if waiting_items:
        #             # 점수가 가장 낮은 항목 찾기
        #             worst_item = min(waiting_items, key=lambda x: float(x.get("before_score", 10.0)))
        #             worst_item["status"] = "approved"
        #             
        #             logging.info(f"  🤖 [자동 치유] 가장 점수가 낮은 포스팅 자동 승인: {worst_item['title']} ({worst_item['before_score']}점)")
        #             report_to_discord("CEO_STATUS", f"🤖 **[긴급 복구 시스템 가동]**\n애드센스 승인 지연을 막기 위해, 대기열 중 가장 심각한 최저점 포스팅을 1개 자동 승인하여 즉시 리라이트 수술에 들어갑니다.\n👉 **수술 대상**: `{worst_item['title']}` ({worst_item['before_score']}점)")
        #             
        #             pending_file.write_text(json.dumps(p_data, ensure_ascii=False, indent=2), encoding='utf-8')
        # except Exception as e:
        #     logging.warning(f"  ⚠️ 자동 승인 처리 중 오류: {e}")

        return True, 0

    except Exception as e:
        logging.error(f"  감사 루프 오류: {e}")
        return False, 10

# ============================================================
# 승인된 항목 in-place 수정 루프 (새 포스팅 없음)
# ============================================================
def run_approved_rewrites():
    """
    [FIX] CEO는 감사(Audit)만 하고 실제 재포스팅 작업은 Orchestrator(에이전트 스쿼드)에 위임합니다.
    pending_approval.json에서 status==approved 항목을 감지하면:
    1. 02_Checkpoints/[REWRITE]_주제명.json 체크포인트에 post_id, url 등을 미리 생성
    2. 00_Raw/[REWRITE]_주제명.txt 파일 생성하여 Orchestrator(에이전트 스쿼드) 작업 유도
    3. pending_approval.json에서 상태를 'done'으로 변경하여 중복 처리 방지
    """
    pending_file = META_DIR / "pending_approval.json"
    if not pending_file.exists():
        return
    
    try:
        pending_data = json.loads(pending_file.read_text(encoding='utf-8'))
    except:
        return
    
    approved = [p for p in pending_data if p.get("status") == "approved" and p.get("action") == "UPDATE"]
    if not approved:
        return
        
    logging.info(f"  📢 승인된 재작성 요청 {len(approved)}건 감지 -> 에이전트 스쿼드(Orchestrator)로 이관")
    
    for item in approved:
        topic = item.get("topic", "")
        title = item.get("title", topic)
        post_id = item.get("post_id")
        url = item.get("url", "")
        orig_date = item.get("original_date", "")
        
        if not topic: continue
        
        # 파일명 및 체크포인트명 생성에 안전한 형식으로 변환
        safe_name = re.sub(r'[^\w]', '_', topic)[:50]
        txt_filename = f"[REWRITE]_{safe_name}.txt"
        json_filename = f"[REWRITE]_{safe_name}.json"
        
        txt_path = RAW_DIR / txt_filename
        json_path = BASE_DIR / "02_Checkpoints" / json_filename
        
        logging.info(f"  📬 에이전트 이관 처리: {topic} (Post ID: {post_id})")
        
        # 1. 02_Checkpoints/[REWRITE]_topic.json 파일 생성하여 Orchestrator에 데이터 연동
        cp_data = {
            "task_type": "REWRITE",
            "post_id": post_id,
            "url": url,
            "original_date": orig_date,
            "topic": topic
        }
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(cp_data, ensure_ascii=False, indent=2), encoding='utf-8')
            logging.info(f"    - 체크포인트 미리 생성 완료: {json_filename}")
        except Exception as e:
            logging.error(f"    - 체크포인트 생성 실패: {e}")
            continue
            
        # 2. 00_Raw/[REWRITE]_topic.txt 파일 생성하여 에이전트 구동
        try:
            txt_path.write_text(topic, encoding='utf-8')
            logging.info(f"    - Raw 트리거 파일 생성 완료: {txt_filename}")
            
            # 디스코드 알림
            report_to_discord("CEO_Auditor", 
                f"🔀 **[에이전트 스쿼드 호출]**\n"
                f"CEO의 감사를 통과하고 승인된 포스팅에 대해 **실제 재저술 작업을 위해 10-에이전트 스쿼드**를 호출했습니다.\n"
                f"👉 **대상**: `{title}`\n"
                f"👉 **작업**: 10단계 파이프라인 가동 (수행 후 제자리 업데이트)")
                
            item["status"] = "done" # 에이전트에게 작업을 이관했으므로 CEO 기준으로는 처리 완료
            
        except Exception as e:
            logging.error(f"    - Raw 파일 생성 실패: {e}")
            # 실패 시 체크포인트 롤백
            if json_path.exists(): json_path.unlink()
            
    # 결과 저장
    pending_file.write_text(json.dumps(pending_data, ensure_ascii=False, indent=2), encoding='utf-8')


def audit_newly_published_posts(trigger_data=None):
    """새롭게 발행된(또는 published_links.json에 방금 등록된) 신규 포스팅 실시간 감사 및 분류, 강화학습 반영"""
    links_file = META_DIR / "published_links.json"
    if not links_file.exists(): return
    
    try:
        links = json.loads(links_file.read_text(encoding='utf-8'))
    except: return
    
    target_items = []
    
    if trigger_data:
        # 트리거 데이터가 전달된 경우 강제 채점 대상 지정 및 DB 정합성 강제 조정
        url = trigger_data.get("url")
        title = trigger_data.get("title")
        topic = trigger_data.get("topic")
        post_id = trigger_data.get("post_id")
        
        # url 기준 매칭
        matched_item = next((item for item in links if item.get("url") == url), None)
        if matched_item:
            matched_item["title"] = title
            matched_item["topic"] = topic
            matched_item["date"] = datetime.now().strftime("%Y-%m-%d")
            if post_id: matched_item["post_id"] = post_id
            matched_item.pop("ceo_status", None)
            matched_item.pop("ceo_score", None)
            target_items.append(matched_item)
            logging.info(f"🎯 [트리거 강제 감사] 기존 항목 초기화 완료: {title}")
        else:
            new_item = {
                "title": title,
                "url": url,
                "topic": topic,
                "nutrients": trigger_data.get("nutrients", []),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "category": trigger_data.get("category", "GENERAL")
            }
            if post_id: new_item["post_id"] = post_id
            links.append(new_item)
            target_items.append(new_item)
            logging.info(f"🎯 [트리거 강제 감사] 신규 항목 추가 완료: {title}")
    else:
        # 폴백: 미채점 오늘/어제 기사 자동 수집
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        for item in links:
            if "ceo_status" not in item and item.get("date") in [today_str, yesterday_str]:
                target_items.append(item)
                
    if not target_items:
        logging.info("  💤 감사 대상 신규 포스팅이 없습니다.")
        return
        
    for item in target_items:
        title = item.get("title")
        url = item.get("url")
        topic = item.get("topic", title)
        post_id = item.get("post_id")
        
        logging.info(f"✨ [신규 품질 감사] 시작: {title}")
        report_to_discord("CEO_Auditor", f"📢 **[신규 포스팅 감지]** 1차 품질 감사 및 분류 작업을 시작합니다:\n**{title}**")
        
        # 본문 수집 (Blogger API 우선)
        post_html = ""
        if post_id:
            try:
                svc = get_blogger_service()
                if svc:
                    post_data = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
                    post_html = post_data.get("content", "")
            except Exception as e:
                logging.warning(f"  신규글 API 수집 실패: {e}")
                
        if not post_html and url:
            try:
                svc = get_blogger_service()
                if svc:
                    path = url.replace("https://www.nutristacklab.com", "")
                    post_data = svc.posts().getByPath(blogId=BLOG_ID, path=path).execute()
                    post_html = post_data.get("content", "")
                    item["post_id"] = post_data.get("id")
            except Exception as e:
                logging.warning(f"  신규글 Path API 수집 실패: {e}")
                
        if not post_html:
            # 크롤링 폴백
            try:
                res = requests.get(url, timeout=15)
                if res.status_code == 200:
                    post_html = res.text
            except Exception as e:
                logging.error(f"  신규글 크롤링 수집 실패: {e}")
                
        if not post_html:
            logging.warning(f"  신규글 본문 수집 실패로 감사를 건너뜁니다.")
            continue
            
        # HTML 정제 (의미 있는 HTML 태그, JSON-LD, TOC 등 보존)
        text_content = clean_html_for_audit(post_html)
        
        # 감사관 에이전트 채점
        auditor_sys = load_agent_with_lessons("11_CEO_Auditor.md")
        full_prompt = (
            f"제목: {title}\n"
            f"주제: {topic}\n"
            f"URL: {url}\n\n"
            f"[신규 기사 본문]\n{text_content[:30000]}\n\n"
            f"위 신규 기사 본문만을 정밀히 분석하고 품질을 채점하라."
        )
        report = ask_ai(full_prompt, auditor_sys, HEAVY_MODEL, timeout=600)
        if not report:
            logging.warning("  AI 응답이 비어있어 감사를 연기합니다.")
            continue
            
        # ── [프로그램 기반 추가 엄격 필터링]
        override_reasons = []
        
        # 1) 단어 수 1000 미만 즉시 탈락
        calculated_words = len(text_content.split())
        if calculated_words < 1000:
            override_reasons.append(f"단어 수 1000 미만 ({calculated_words}단어)")
            
        # 2) 제목 오염 즉시 탈락
        title_lower = title.lower()
        polluted_keywords = ["stopped", "common", "comparing", "taking", "vs and"]
        for pk in polluted_keywords:
            if re.search(r'\b' + re.escape(pk) + r'\b', title_lower):
                override_reasons.append(f"제목 오염 키워드 검출 ('{pk}')")
        
        # 3) 가상 저널 인용 즉시 탈락
        text_lower = text_content.lower()
        virtual_patterns = [
            "nordic journal of", "journal of nordic",
            "tromsø 연구", "tromso 연구", "tromsø study", "tromso study"
        ]
        for vp in virtual_patterns:
            if vp in text_lower:
                override_reasons.append(f"가상 저널/연구 인용 의심 검출 ('{vp}')")
                
        # 4) CSS # 누락 여부 검사
        if re.search(r'(?:background|color|border)[^:;]*:\s*[a-fA-F0-9]{6}\b', post_html):
            override_reasons.append("CSS 컬러 코드 내 # 누락 검출")
            
        # 5) TOC href anchor # 누락 검사
        if re.search(r'href=["\']sec\d+["\']', post_html):
            override_reasons.append("목차(TOC) 내부 anchor 링크 # 누락 검출 (href='sec0')")
            
        # 6) 내부 링크 / 본문 내 화살표 엔티티 오염 검출
        if "→" in post_html or "&8594;" in post_html:
            override_reasons.append("화살표 엔티티 오염 검출 (→ 또는 &8594; 사용됨, &#8594; 권장)")
            
        # 7) Google Drive 구버전 썸네일 이미지 링크 검출
        if "drive.google.com/thumbnail" in post_html:
            override_reasons.append("구버전 Google Drive 이미지 링크 검출")
            
        # 8) PMID 번호 40,000,000 초과 가상 PMID 검출
        pmids = re.findall(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', post_html)
        for pmid in pmids:
            if int(pmid) > 40000000:
                override_reasons.append(f"가상 PMID 의심 번호 검출 ({pmid} > 40,000,000)")
                
        # 9) 빈 섹션 (30단어 미만) 검출
        h2_sections = re.findall(r'<h2[^>]*>.*?</h2>(.*?)(?=<h2|<hr|$)', post_html, re.DOTALL)
        for sec in h2_sections:
            text = re.sub(r'<[^>]+>', ' ', sec).strip()
            if len(text.split()) < 30:
                override_reasons.append("빈 섹션 감지 (텍스트 30단어 미만)")
                
        # 점수 및 상태 파싱
        score_match = re.search(r'SCORE:\s*([\d.]+)', report)
        score = float(score_match.group(1)) if score_match else 5.0
        
        # AI 판단 status 파싱 (KEEP | REWRITE)
        status_match = re.search(r'STATUS:\s*(\w+)', report)
        ai_status = status_match.group(1) if status_match else "KEEP"
        
        # 강제 탈락 발동 여부
        if override_reasons:
            original_score = score
            score = min(score, 5.9) # 강제 탈락이므로 점수 상한선을 5.9(D등급)로 강제 조정
            item["ceo_status"] = "audit_target"
            item["ceo_score"] = score
            status_korean = f"⚠️ 강제 감사 대상 (프로그램 규칙 위반 적발)"
            arrow = "🚨"
            report = re.sub(r'SCORE:\s*[\d.]+/10', f'SCORE: {score}/10 (AI 원평가: {original_score}/10 - 프로그램 강제 강등 🚨)', report)
            report += f"\n\n[프로그램 엄격 규칙 위반 적발]:\n" + "\n".join(f"- {r}" for r in override_reasons)
        # 기존 AI 판단에 따른 점수 기준 분류 (8.0점 이상이면 감사면제, 미만이면 감사 대상)
        elif score >= 8.0 and ai_status == "KEEP":
            item["ceo_status"] = "audit_exempt" # 감사 제외 대상 (품질 최우수)
            item["ceo_score"] = score
            status_korean = "🏆 감사 제외 대상 (품질 최우수)"
            arrow = "🌟"
        else:
            item["ceo_status"] = "audit_target" # 감사 대상 (향후 리라이트 후보군)
            item["ceo_score"] = score
            status_korean = "⚠️ 감사 대상 (품질 보강 필요)"
            arrow = "📢"
            
        # 디스코드 채점 보고서 3분할 출력
        seo = re.search(r'SEO:\s*([\d.]+)', report)
        human = re.search(r'인간\s*느낌:\s*([\d.]+)', report)
        footprint = re.search(r'AI\s*footprint:\s*([\d.]+)', report)
        safety = re.search(r'건강\s*(?:블로그\s*)?안전성\s*:\s*([\d.]+)', report)
        adsense = re.search(r'애드센스\s*(?:친화성)?\s*:\s*([\d.]+)', report)
        
        reason = report.split("\n", 2)[-1].strip()
        reason = reason.replace("STATUS: KEEP", "최종 판단 (STATUS): ✅ 감사 통과 (유지)")
        reason = reason.replace("STATUS: REWRITE", "최종 판단 (STATUS): ⚠️ 수정 및 리라이트 대상")
        reason = reason.replace("STATUS: RESTORE_IMAGE", "최종 판단 (STATUS): 🖼️ 이미지 복원 대상")
        reason = reason.replace("SCORE:", "종합 평점 (SCORE):")
        
        override_warning = ""
        if override_reasons:
            override_warning = (
                f"🚨 **[프로그램 규칙 위반 강제 강등]**\n"
                f"원래 AI 평점 평균은 **{original_score}/10**이었으나, 아래 규칙 위반으로 인해 최종 점수가 **5.9점**으로 강제 조정되었습니다:\n"
                + "\n".join(f"- ❌ {r}" for r in override_reasons)
                + "\n\n"
            )
            
        ai_avg = original_score if override_reasons else score
        summary_card = (
            f"**[신규 포스팅 1차 감사 완료]**\n"
            f"제목: **{title}**\n"
            f"분류 결과: **{arrow} {status_korean}**\n"
            f"최종 보정 점수: **{score}/10**\n"
            f"📊 **AI 순수 평가 평균**: **{ai_avg}/10** (아래 개별 점수의 수학적 평균)\n\n"
            f"{override_warning}"
            f"📈 **세부 품질 지표**\n"
            f"- SEO: `{seo.group(1) if seo else 'N/A'}/10`\n"
            f"- 인간 느낌: `{human.group(1) if human else 'N/A'}/10`\n"
            f"- AI 흔적: `{footprint.group(1) if footprint else 'N/A'}/10`\n"
            f"- 건강 안전성: `{safety.group(1) if safety else 'N/A'}/10`\n"
            f"- 애드센스 친화성: `{adsense.group(1) if adsense else 'N/A'}/10`"
        )
        report_to_discord("CEO_Auditor", summary_card)
        
        # 상세 분석 보고서 발송 (2,000자 제한 자동분할)
        report_to_discord("CEO_Auditor_Detail", f"**[품질 분석 및 사유]**\n{reason}")
        
        # ── [강화 학습] 8점 미만일 시 피드백 각인 피드백 루프 작동
        if score < 8.0:
            try:
                logging.info("  🧠 [강화학습 각인 시작] 낮은 점수 항목의 사유를 로컬 에이전트 피드백에 저장합니다.")
                lessons_parsed = {}
                
                # 피드백 내용 파싱 및 분류 요청
                structured = ask_ai(
                    f"다음 신규 기사 채점 반려 사유를 에이전트별(Writer, Researcher, SEO)로 분류해서 JSON으로 반환하라.\n반려 사유:\n{reason}\n\n"
                    f'출력 형식 (JSON): {{"Writer": "글쓰기 개선 지시", "Researcher": "리서치 개선 지시", "SEO": "SEO 개선 지시"}}\n'
                    f"JSON만 출력하고 설명은 일절 생략하라.",
                    "JSON만 출력하는 AI 분류기입니다.", LIGHT_MODEL, timeout=60
                )
                
                match = re.search(r'\{.*\}', structured, re.DOTALL)
                if match:
                    try:
                        lessons_parsed = json.loads(match.group())
                    except Exception as json_err:
                        logging.warning(f"JSON 파싱 에러 (매치 찾았으나 실패): {json_err}")
                        lessons_parsed = {"Writer": reason[:300]}
                else:
                    lessons_parsed = {"Writer": reason[:300]}
                    
                lessons_file = META_DIR / "agent_lessons.json"
                lessons = {}
                if lessons_file.exists():
                    try: lessons = json.loads(lessons_file.read_text(encoding='utf-8'))
                    except: lessons = {}
                    
                today_str = datetime.now().strftime("%Y-%m-%d")
                
                AGENT_FILE_MAP = {
                    "Writer": "03_Writer_Gardener",
                    "Researcher": "02_Researcher_Synergy",
                    "SEO": "04_SEO_Optimizer"
                }
                
                seo_val = seo.group(1) if seo else "?"
                hum_val = human.group(1) if human else "?"
                foot_val = footprint.group(1) if footprint else "?"
                safe_val = safety.group(1) if safety else "?"
                ads_val = adsense.group(1) if adsense else "?"
                score_summary = f"[점수: {score}/10 | 기술: {seo_val}, AI흔적: {foot_val}, 품질: {safe_val}, 애드센스: {ads_val}, 인간느낌: {hum_val}]"
                
                for role, feedback in lessons_parsed.items():
                    if isinstance(feedback, (dict, list)):
                        feedback_str = json.dumps(feedback, ensure_ascii=False)
                    else:
                        feedback_str = str(feedback)
                        
                    if role in AGENT_FILE_MAP and feedback_str.strip():
                        agent_key = AGENT_FILE_MAP[role]
                        if agent_key not in lessons:
                            lessons[agent_key] = []
                        lessons[agent_key].append({
                            "date": today_str,
                            "lesson": f"[{title[:30]}] {score_summary} 사유: {feedback_str.strip()}"
                        })
                        logging.info(f"    - [{agent_key}]에 피드백 주입 완료")
                        
                lessons_file.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding='utf-8')
                report_to_discord("CEO_Reinforcement", f"🧠 **[강화학습 피드백 각인]** {title[:40]} 글의 점수 미달 항목 피드백을 Writer/Researcher/SEO 에이전트의 뇌(`agent_lessons.json`)에 영구 각인했습니다. 다음 기사 집필 시 자동 진화하여 반영됩니다.")
            except Exception as e:
                logging.warning(f"  강화학습 각인 실패: {e}")
                
        # ── [개선] 매 포스팅 감사 완료 직후 결과를 파일에 즉시 기록하여 보존
        links_file.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding='utf-8')
        logging.info(f"💾 [{title[:30]}] 감사 상태 저장 완료")

# ============================================================
# 비즈니스 헬스 체크# ============================================================
# 비즈니스 헬스 체크 (AdSense & SEO Focus)
# ============================================================
def check_business_health():
    """애드센스 수익화 및 SEO 병목 현상 감지"""
    # 1. 오케스트레이터 로그 확인
    orch_log = BASE_DIR / "orchestrator.log"
    if orch_log.exists():
        content = orch_log.read_text(encoding='utf-8')
        last_logs = content[-3000:]
        
        # 애드센스 위험 요소 (이미지 깨짐, 빈 섹션 등)
        if "src=\"\"" in last_logs or "EMPTY_SECTION" in last_logs:
            report_to_discord("CEO_AdSense_Alert", "⚠️ **가시성 문제 감지!** 빈 이미지 태그나 섹션이 발견되었습니다. 애드센스 가독성 점수에 악영향을 줄 수 있으니 확인이 필요합니다.")
        
        # SEO 반려 감지
        if "REJECTED" in last_logs:
            rejections = last_logs.count("REJECTED")
            if rejections > 2:
                report_to_discord("CEO_SEO_Alert", f"🔍 **품질 가이드라인 위반 감지!** 최근 {rejections}개의 포스팅이 크리틱에 의해 반려되었습니다. 글의 전문성을 높여야 합니다.")

    # 2. 성능 DB 확인 (애드센스 최적 단어 수 1500+ 체크)
    perf_file = META_DIR / "performance_db.json"
    if perf_file.exists():
        try:
            db = json.loads(perf_file.read_text(encoding='utf-8'))
            recent = db[-5:]
            low_word_posts = [p for p in recent if p.get("word_count", 0) < 1500]
            if len(low_word_posts) >= 3:
                report_to_discord("CEO_AdSense_Tip", "💡 **애드센스 수익화 팁**: 최근 포스팅들의 분량이 짧습니다(1,500단어 미만). 더 풍부한 정보성 콘텐츠를 채워야 광고 수익이 극대화됩니다.")
        except: pass

# ============================================================
# 업무 일지 생성 (Daily Work Log)
# ============================================================
def send_daily_work_log():
    """오늘 하루의 활동을 요약하여 보고"""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    # 1. 오늘 발행된 글 확인
    links_file = META_DIR / "published_links.json"
    today_posts = []
    if links_file.exists():
        try:
            links = json.loads(links_file.read_text(encoding='utf-8'))
            today_posts = [l for l in links if l.get("date") == today_str]
        except: pass

    # 2. 오늘 진행된 감사(Audit) 요약
    # 로그 파일에서 오늘 날짜의 감사 결과 추출
    audit_count = 0
    rewrite_count = 0
    if LOG_FILE.exists():
        try:
            logs = LOG_FILE.read_text(encoding='utf-8')
            today_logs = [line for line in logs.splitlines() if today_str in line]
            audit_count = sum(1 for l in today_logs if "📊 감사 결과" in l)
            rewrite_count = sum(1 for l in today_logs if "🚨 자율 수정 결정" in l or "STATUS: REWRITE" in l)
        except: pass

    # 3. 보고서 작성
    report = f"📋 **{today_str} NutriStack 업무 일지**\n\n"
    report += f"✅ **오늘의 발행 성과 ({len(today_posts)}건)**\n"
    if today_posts:
        for p in today_posts:
            report += f"- {p['title']}\n"
    else:
        report += "- 오늘 발행된 포스팅이 없습니다.\n"
    
    report += f"\n🔍 **자율 교정 현황**\n"
    report += f"- 오늘 총 {audit_count}개의 과거 포스팅 검수 완료\n"
    report += f"- 그 중 {rewrite_count}개의 포스팅을 수정 대기열에 추가\n"
    
    report += f"\n⚙️ **시스템 상태**\n"
    task_count = len(list(RAW_DIR.glob("*.txt")))
    report += f"- 현재 대기 중인 작업: {task_count}개\n"
    report += f"- 자율 주행 엔진: 정상 작동 중 (v1.0)\n"

    report_to_discord("CEO_DAILY_REPORT", report)
    logging.info("  📅 일일 업무 일지 발송 완료")

# ============================================================
# 메인 루프
# ============================================================
def get_next_audit_time(now):
    """현재 시간 기준으로 다음 3의 배수 정각 시간 반환 (0,3,6,9,12,15,18,21)"""
    next_hour = ((now.hour // 3) + 1) * 3
    if next_hour >= 24:
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
def run_autonomous_ceo():
    logging.info("="*50)
    logging.info("🤖 NutriStack Lab Autonomous CEO v1.0 가동")
    logging.info("  📊 자율 품질 감사 및 자가 치유 모드 활성화")
    logging.info("  🏥 비즈니스 헬스 체크 활성화")
    logging.info("  📅 매일 19:00 업무 일지 보고 활성화")
    logging.info("="*50)
    
    report_to_discord("CEO_SYSTEM", "🚀 **Autonomous CEO 시스템이 가동되었습니다.**")

    last_log_day = -1
    last_health_check_hour = -1
    next_audit_time = get_next_audit_time(datetime.now())
    logging.info(f"  ⏳ 다음 정기 감사 예정 시간: {next_audit_time.strftime('%Y-%m-%d %H:%M:%S')}")

    while True:
        now = datetime.now()
        
        # 0. 신규 포스팅 실시간 품질 감사 & 분류 & 에이전트 진화 (트리거 파일 감지 시에만 작동)
        trigger_file = META_DIR / "new_post_trigger.json"
        if trigger_file.exists():
            try:
                logging.info("📡 [CEO] 신규 포스팅 발행 신호 감지! 1차 실시간 감사 및 분류 시작.")
                try:
                    trigger_data = json.loads(trigger_file.read_text(encoding='utf-8'))
                except Exception as e:
                    logging.warning(f"  트리거 파일 파싱 오류: {e}")
                    trigger_data = None
                audit_newly_published_posts(trigger_data)
                if trigger_file.exists():
                    trigger_file.unlink()
                logging.info("📡 [CEO] 1차 실시간 감사 완료 및 신호 트리거 제거 완료.")
            except Exception as e:
                logging.error(f"신규 포스팅 실시간 감사 오류: {e}")
        
        # 1. 비즈니스 헬스 체크 (매 1시간마다 1회 실행)
        if now.hour != last_health_check_hour:
            check_business_health()
            last_health_check_hour = now.hour
        
        # 2. 품질 감사 루프 (지정된 시간에만 작동, 재시작 시 난사 방지)
        if now >= next_audit_time:
            success, wait_min = run_audit_cycle()
            if success:
                next_audit_time = get_next_audit_time(datetime.now())
                logging.info(f"  ⏳ 다음 정기 감사 예약: {next_audit_time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                next_audit_time = now + timedelta(minutes=wait_min)
                logging.info(f"  ⚠️ 감사 지연, 재시도 예약: {next_audit_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 3. 승인된 항목 in-place 수정 실행 (사용자 요청으로 보류 - 오직 감사만 수행)
        # run_approved_rewrites()
            
        # 4. 매일 19:00 업무 일지 보고
        if now.hour == 19 and now.minute == 0 and now.day != last_log_day:
            send_daily_work_log()
            last_log_day = now.day

        # 5. 오전 09:00 상태 보고
        if now.hour == 9 and now.minute == 0:
            report_to_discord("CEO_STATUS", f"자율 주행 엔진 가동 중... (대기 작업: {len(list(RAW_DIR.glob('*.txt')))}개)")
            time.sleep(60)

        time.sleep(60) # 1분마다 루프

if __name__ == "__main__":
    run_autonomous_ceo()
