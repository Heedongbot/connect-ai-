import os
import re
import json
import logging
import asyncio
import pickle
import psutil
import subprocess
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import requests as _req

try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build as _goog_build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False

HERMES_QUEUE_FILE  = Path("20_Meta/hermes_queue.json")
_QUEUE_LOCK_FILE   = Path("20_Meta/hermes_queue.lock")
PUBLISHED_LINKS    = Path("20_Meta/published_links.json")
CODE_LESSONS_FILE  = Path("20_Meta/code_fix_lessons.json")
TOKEN_FILE         = Path("token.pickle")
BLOG_ID            = "2812259517039331714"
HERMES_POLL_SEC    = 300  # 5분마다 큐 감시
MODEL_CLAUDE_CODE  = "claude-haiku-4-5-20251001"
QWEN3_CONFIDENCE_THRESHOLD = 8  # 이 이상이면 Qwen3 단독 처리

# 자동 수정 가능 카테고리
AUTO_FIX_CATS     = {"D2", "E1", "B1", "A1", "A2"}
# 알림만 (자동수정 불가)
NOTIFY_ONLY_CATS  = {"C3", "D1", "C4"}
# Hermes 최대 재시도 횟수 (초과 시 "exhausted" — 더 이상 시도 안 함)
HERMES_MAX_RETRIES = 3
# 재시도 불가 상태 (이 상태면 pending으로 재설정 금지)
HERMES_TERMINAL_STATES = {"exhausted", "done"}
def ask_ai(prompt, system_prompt="", model="qwen2:7b-instruct-q4_0", **kwargs):
    try:
        r = _req.post("http://localhost:11434/api/generate", json={
            "model": model, "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
            "stream": False
        }, timeout=120)
        return r.json().get("response", "")
    except Exception as e:
        return f"[오류: {e}]"


def _load_anthropic_key() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def ask_claude_code(prompt: str, system: str = "") -> str:
    """Claude API 코드 수정 전용. 실패 시 Qwen3 폴백."""
    if not _ANTHROPIC_AVAILABLE:
        return ask_ai(prompt, system, MODEL_HERMES)
    key = _load_anthropic_key()
    if not key:
        logger.warning("[Claude] API 키 없음 → Qwen3 폴백")
        return ask_ai(prompt, system, MODEL_HERMES)
    try:
        client = _anthropic.Anthropic(api_key=key)
        kwargs = {"model": MODEL_CLAUDE_CODE, "max_tokens": 8192,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        return client.messages.create(**kwargs).content[0].text.strip()
    except Exception as e:
        logger.warning(f"[Claude API 오류] {e} → Qwen3 폴백")
        return ask_ai(prompt, system, MODEL_HERMES)


def _acquire_queue_lock(timeout: int = 10) -> bool:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(str(_QUEUE_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False

def _release_queue_lock():
    try:
        _QUEUE_LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def load_code_lessons() -> list:
    if CODE_LESSONS_FILE.exists():
        try:
            return json.loads(CODE_LESSONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_code_lesson(problem: str, analysis: str, fix_summary: str, used_claude: bool):
    lessons = load_code_lessons()
    lessons.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "problem": problem[:200],
        "qwen3_analysis": analysis[:500],
        "fix_summary": fix_summary[:300],
        "used_claude": used_claude,
    })
    lessons = lessons[-50:]  # 최근 50개 유지
    CODE_LESSONS_FILE.write_text(
        json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"[코드 학습] 저장 완료 — 총 {len(lessons)}개 누적, Claude={used_claude}")

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("HernexAgent")

# 헤넥스 기본 LLM 모델 지정 (속도 향상을 위해 가벼운 qwen2:7b-instruct-q4_0 사용)
MODEL_HERNEX = "qwen2:7b-instruct-q4_0"
# 코딩 및 코드 자가 치유(Hermes)를 위한 고성능 14B 모델 지정
MODEL_HERMES = "qwen3:14b-q4_K_M"

CONFIG_FILE = "telegram_config.json"
HERNEX_MEMORY_FILE = "20_Meta/hernex_memory.json"

SCRIPTS = {
    "orchestrator":   {"file": "00_NutriStack_Grand_Orchestrator_v5.py", "name": "오케스트레이터"},
    "scheduler":      {"file": "daily_scheduler_v5.py",                  "name": "데일리 스케줄러"},
    "discord":        {"file": "bot_start.py",                           "name": "디스코드 봇"},
    "morning_report": {"file": "morning_report.py",                      "name": "아침 리포트"},
    "ceo":            {"file": "00_NutriStack_Autonomous_CEO_v1.py",      "name": "Autonomous CEO"},
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_memory():
    os.makedirs("20_Meta", exist_ok=True)
    if os.path.exists(HERNEX_MEMORY_FILE):
        try:
            with open(HERNEX_MEMORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "master_preference": "마스터는 블로그의 품질과 E-E-A-T 기준 준수를 가장 중요시합니다.",
        "blog_structure": "NutriStack Lab 블로그. Qwen3 오케스트레이터가 글을 자동으로 생성하고 검수 후 발행함.",
        "recent_events": []
    }

def save_memory(mem):
    with open(HERNEX_MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)

def get_process_status():
    status = {}
    running_cmds = []
    for p in psutil.process_iter(attrs=['pid', 'name', 'cmdline']):
        try:
            if p.info['name'] and 'python' in p.info['name'].lower():
                cmd = p.info['cmdline']
                if cmd:
                    running_cmds.append((p.info['pid'], cmd))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    for key, info in SCRIPTS.items():
        is_running = False
        pid = None
        for r_pid, cmd in running_cmds:
            if any(info["file"] in arg for arg in cmd):
                is_running = True
                pid = r_pid
                break
        status[key] = {"running": is_running, "pid": pid, "name": info["name"], "file": info["file"]}
    return status

def start_process(key):
    status = get_process_status()
    if key not in status:
        return False, "존재하지 않는 프로세스 키입니다."
    if status[key]["running"]:
        return False, f"이미 {status[key]['name']}가 실행 중입니다. (PID: {status[key]['pid']})"
        
    script_file = status[key]["file"]
    try:
        subprocess.Popen(
            ["python", script_file],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=os.path.abspath(".")
        )
        return True, f"🟢 **{status[key]['name']}**를 새로운 콘솔 창에서 기동했습니다."
    except Exception as e:
        return False, f"❌ 실행 중 에러 발생: {str(e)}"

def stop_process(key):
    status = get_process_status()
    if key not in status:
        return False, "존재하지 않는 프로세스 키입니다."
    if not status[key]["running"]:
        return False, f"이미 {status[key]['name']}가 정지되어 있습니다."
        
    pid = status[key]["pid"]
    try:
        p = psutil.Process(pid)
        p.terminate()
        return True, f"🔴 **{status[key]['name']}** (PID: {pid})를 정지했습니다."
    except Exception as e:
        return False, f"❌ 정지 중 에러 발생: {str(e)}"

def generate_ceo_report():
    import json
    from pathlib import Path
    
    perf_path = Path("20_Meta/performance_db.json")
    pending_path = Path("20_Meta/pending_approval.json")
    
    report_lines = ["📊 **NutriStack Lab - CEO 자율 감사 리포트**\n"]
    
    # 1. performance_db.json 파싱
    if perf_path.exists():
        try:
            with open(perf_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # CEO 감사 기록만 필터링
            ceo_records = [r for r in data if r.get("source") == "CEO_Auditor"]
            
            if ceo_records:
                # 점수 평균 계산
                scores = []
                for r in ceo_records:
                    s = r.get("scores", {})
                    if isinstance(s, dict) and "total" in s:
                        scores.append(s["total"])
                
                avg_score = sum(scores) / len(scores) if scores else 0.0
                report_lines.append(f"• **평균 품질 점수**: `{avg_score:.2f} / 10.0` (감사 건수: {len(ceo_records)}개)")
                
                # 최신 감사 글 3개
                report_lines.append("\n🔍 **최근 감사 완료 포스트 (최신 3개):**")
                for r in sorted(ceo_records, key=lambda x: x.get("audited_at", ""), reverse=True)[:3]:
                    title = r.get("title", "제목 없음").strip()
                    total_s = r.get("scores", {}).get("total", 0.0)
                    status = r.get("status", "KEEP")
                    status_emoji = "🚨 재작성 필요" if status == "REWRITE" else "✅ 유지(KEEP)"
                    report_lines.append(f"  - [{total_s:.1f}점] {title} ({status_emoji})")
            else:
                report_lines.append("• 아직 CEO 자율 감사 기록이 존재하지 않습니다.")
        except Exception as e:
            report_lines.append(f"⚠️ performance_db.json 읽기 실패: {str(e)}")
    else:
        report_lines.append("• `performance_db.json` 파일이 존재하지 않습니다.")
        
    # 2. pending_approval.json 파싱
    if pending_path.exists():
        try:
            with open(pending_path, "r", encoding="utf-8") as f:
                pending_data = json.load(f)
            
            waiting_rewrites = [p for p in pending_data if p.get("status") == "waiting" and p.get("type") == "REWRITE"]
            done_rewrites = [p for p in pending_data if p.get("status") == "done" and p.get("type") == "REWRITE"]
            
            report_lines.append(f"\n🔄 **재작성(REWRITE) 상태:**")
            report_lines.append(f"  - ⏳ 승인 대기 중 (waiting): `{len(waiting_rewrites)}`개")
            report_lines.append(f"  - 완료된 재작성 (done): `{len(done_rewrites)}`개")
            
            if waiting_rewrites:
                report_lines.append("\n📋 **대기 중인 재작성 대상 (최대 3개):**")
                for w in waiting_rewrites[:3]:
                    topic = w.get("topic", "주제 없음")
                    before_score = w.get("before_score", "알수없음")
                    report_lines.append(f"  - `{topic}` (이전 점수: {before_score})")
        except Exception as e:
            report_lines.append(f"⚠️ pending_approval.json 읽기 실패: {str(e)}")
    else:
        report_lines.append("• `pending_approval.json` 파일이 존재하지 않습니다.")
        
    return "\n".join(report_lines)

async def ceo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = generate_ceo_report()
    await update.message.reply_text(report, parse_mode='Markdown')

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import json
    from pathlib import Path
    
    pending_path = Path("20_Meta/pending_approval.json")
    if not pending_path.exists():
        await update.message.reply_text("❌ `pending_approval.json` 파일이 존재하지 않습니다.")
        return
        
    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            pending_data = json.load(f)
    except Exception as e:
        await update.message.reply_text(f"❌ 대기열 로드 실패: {str(e)}")
        return
        
    waiting_items = [p for p in pending_data if p.get("status") == "waiting" and p.get("type") == "REWRITE"]
    
    args = context.args
    if not args:
        if not waiting_items:
            await update.message.reply_text("⏳ 현재 승인 대기 중인 리라이트 대상이 없습니다.")
            return
            
        lines = ["⏳ **승인 대기 중인 리라이트 대상 목록:**\n"]
        for idx, item in enumerate(waiting_items, 1):
            lines.append(f"  {idx}. [이전점수: {item.get('before_score', '?')}] {item.get('topic')}")
        lines.append("\n💡 승인하려면 `/approve [번호]` 또는 `/approve [주제 키워드]`를 입력하세요.")
        await update.message.reply_text("\n".join(lines))
        return
        
    target_item = None
    arg_str = " ".join(args)
    
    if arg_str.isdigit():
        idx = int(arg_str) - 1
        if 0 <= idx < len(waiting_items):
            target_item = waiting_items[idx]
            
    if not target_item:
        for item in waiting_items:
            if arg_str.lower() in item.get("topic", "").lower() or arg_str.lower() in item.get("title", "").lower():
                target_item = item
                break
                
    if not target_item:
        await update.message.reply_text(f"❌ 대기열에서 '{arg_str}'에 매칭되는 항목을 찾을 수 없습니다.")
        return
        
    for p in pending_data:
        if p.get("topic") == target_item.get("topic") and p.get("status") == "waiting":
            p["status"] = "approved"
            p["approved_at"] = datetime.now().isoformat()
            break
            
    try:
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, ensure_ascii=False, indent=2)
        
        await update.message.reply_text(
            f"✅ **'{target_item.get('topic')}' 재작성이 승인되었습니다.**\n"
            "백그라운드에서 오케스트레이터(10-에이전트 스쿼드)가 가동되어 제자리 업데이트를 시작합니다!"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 승인 저장 실패: {str(e)}")

async def audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import json
    from pathlib import Path
    
    args = context.args
    if not args:
        await update.message.reply_text("💡 감사할 포스팅의 URL을 입력하세요.\n예: `/audit https://www.nutristacklab.com/2026/03/...html`")
        return
        
    target_url = args[0].strip()
    
    links_path = Path("20_Meta/published_links.json")
    if not links_path.exists():
        await update.message.reply_text("❌ `published_links.json` 파일이 존재하지 않습니다.")
        return
        
    try:
        with open(links_path, "r", encoding="utf-8") as f:
            links = json.load(f)
    except Exception as e:
        await update.message.reply_text(f"❌ 발행 링크 로드 실패: {str(e)}")
        return
        
    matched_item = None
    for item in links:
        url = item.get("url", "")
        if target_url in url or url in target_url:
            matched_item = item
            break
            
    if not matched_item:
        if "nutristacklab.com" in target_url:
            matched_item = {
                "title": "수동 입력 기사",
                "url": target_url,
                "topic": "수동 감사 요청",
                "nutrients": [],
                "date": datetime.now().strftime("%Y-%m-%d")
            }
        else:
            await update.message.reply_text("❌ `nutristacklab.com` 도메인의 유효한 발행 URL을 입력해주세요.")
            return
            
    trigger_path = Path("20_Meta/new_post_trigger.json")
    try:
        trigger_data = {
            "title": matched_item.get("title", "수동 감사 기사"),
            "url": matched_item.get("url"),
            "topic": matched_item.get("topic", "수동 감사"),
            "nutrients": matched_item.get("nutrients", []),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "post_id": matched_item.get("post_id")
        }
        with open(trigger_path, "w", encoding="utf-8") as f:
            json.dump(trigger_data, f, ensure_ascii=False, indent=2)
            
        await update.message.reply_text(
            f"📡 **'{trigger_data['title']}'**에 대한 수동 품질 감사를 요청했습니다.\n"
            "백그라운드에서 실행 중인 CEO Auditor가 약 1분 이내에 기사를 분석하고 결과를 Discord/DB에 보고합니다."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 감사 트리거 작성 실패: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🤖 **[Hernex Agent (헤넥스 에이전트) 가동]**\n\n"
        "안녕하세요 마스터님! 저는 **Connect AI**의 신속한 로컬 Qwen3 연동 모델과 "
        "**Hermes**의 강력한 코드/스킬 자가 치유 능력, 그리고 **시스템 제어/감시 엔진**이 하나로 융합되어 태어난 **헤넥스(Hernex)**입니다. 🚀\n\n"
        "💬 **일반 대화:** 그냥 말씀해 주시면, 마스터님의 기억과 취향을 불러와 Qwen3가 맞춤 답변을 드립니다.\n"
        "⚙️ **시스템 제어:** '상태 확인해줘', '오케스트레이터 켜줘', '안 돌아가는 거 다 켜' 등을 통해 직접 프로세스를 감시하고 실행할 수 있습니다.\n"
        "🛠️ **코드 및 스킬 수정:** 에러 수정이나 코드 변경이 필요할 때 문장 앞에 `/hermes` 또는 `/수정`을 달거나, '버그 수정해 줘'처럼 명령해 주시면 자가 치유 엔진(Hermes)이 자동으로 코드를 고칩니다.\n\n"
        "📊 **CEO 리포트 및 감사 승인:**\n"
        "  - `/ceo`: 현재 블로그 품질 평균 및 재작성 대기 목록 조회\n"
        "  - `/approve [번호/키워드]`: 대기 중인 글 재작성 강제 승인 및 오케스트레이터 호출\n"
        "  - `/audit [URL]`: 특정 포스팅을 즉시 수동 감사하여 점수 매기기"
    )
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text
    mem = load_memory()
    
    # 1. Qwen3를 이용해 사용자 발화 목적 라우팅 (시스템 제어 vs 일반 대화 vs 코드 수정)
    classification_prompt = (
        f"유저 명령: {user_query}\n\n"
        "당신은 프로세스 관리 명령 라우터입니다. 유저의 입력이 다음 중 어떤 목적에 해당하는지 분석하여 해당하는 키워드 한 가지만 출력하세요. 설명이나 인사말, 잡담은 절대 하지 마세요.\n\n"
        "- 시스템 상태 확인: STATUS\n"
        "- 특정 프로세스 시작/기동: START:프로세스명 (프로세스명: orchestrator, scheduler, discord, morning_report, ceo, all)\n"
        "- 특정 프로세스 종료: STOP:프로세스명 (프로세스명: orchestrator, scheduler, discord, morning_report, ceo)\n"
        "- 일반 코딩/스킬/버그 수정 명령: HERMES\n"
        "- CEO 감사 결과 및 품질 점수 확인: CEO_REPORT\n"
        "- 일반 질문 및 대화 (위의 기능에 해당하지 않는 잡담/대화): CHAT\n\n"
        "출력 예시: STATUS 또는 START:orchestrator 또는 CHAT"
    )
    
    try:
        class_res = ask_ai(classification_prompt, "당신은 명령 라우팅 키워드 생성기입니다.", MODEL_HERNEX).strip().upper()
        
        route = {"action": "chat"} # 기본값
        if "STATUS" in class_res:
            route = {"action": "status"}
        elif "START" in class_res:
            target = "all"
            for t in ["orchestrator", "scheduler", "discord", "morning_report", "ceo"]:
                if t in class_res.lower():
                    target = t
                    break
            route = {"action": "start", "target": target}
        elif "STOP" in class_res:
            target = "orchestrator"
            for t in ["orchestrator", "scheduler", "discord", "morning_report", "ceo"]:
                if t in class_res.lower():
                    target = t
                    break
            route = {"action": "stop", "target": target}
        elif "HERMES" in class_res:
            route = {"action": "hermes"}
        elif "CEO_REPORT" in class_res:
            route = {"action": "ceo_report"}
    except Exception as e:
        logger.error(f"Routing failed: {e}")
        route = {"action": "chat"}
        
    logger.info(f"Route determined: {route}")
    
    # 2. 라우팅에 따른 액션 실행
    
    # A. 시스템 상태 조회
    if route.get("action") == "status":
        status_msg = await update.message.reply_text("🔍 [Hernex] 시스템 프로세스 상태를 스캔 중입니다...")
        status = get_process_status()
        
        lines = ["🖥️ **NutriStack Lab 시스템 실시간 감시 현황**\n"]
        for key, info in status.items():
            run_str = f"🟢 **구동 중** (PID: {info['pid']})" if info["running"] else "🔴 **정지됨**"
            lines.append(f"• **{info['name']}** (`{info['file']}`): {run_str}")
        
        # 봇 자신도 표시
        lines.append(f"• **Hernex 비서 봇** (`hernex_agent.py`): 🟢 **구동 중** (PID: {os.getpid()})")
        await status_msg.edit_text("\n".join(lines), parse_mode='Markdown')
        
    # B. 프로세스 기동
    elif route.get("action") == "start":
        target = route.get("target", "all")
        status = get_process_status()
        
        if target == "all" or target == "all_stopped":
            started_targets = []
            failed_targets = []
            
            # 정지된 모든 대상을 찾아 차례로 기동
            for key, info in status.items():
                # CEO 루프는 user가 직접 켜달라고 할 때만 기동하도록 예외처리 (CEO는 리소스 점유가 큼)
                if key == "ceo":
                    continue
                if not info["running"]:
                    success, msg = start_process(key)
                    if success:
                        started_targets.append(info["name"])
                    else:
                        failed_targets.append(f"{info['name']} ({msg})")
                        
            if started_targets:
                await update.message.reply_text(f"🚀 **[자동 구동 실행]**\n정지되어 있던 **{', '.join(started_targets)}**를 자동으로 감지하여 새 콘솔 창에서 구동했습니다!")
            else:
                await update.message.reply_text("✅ 이미 모든 주요 프로세스(오케스트레이터, 스케줄러, 디스코드 봇)가 정상 작동 중입니다.")
        else:
            success, msg = start_process(target)
            await update.message.reply_text(msg)
            
    # C. 프로세스 종료
    elif route.get("action") == "stop":
        target = route.get("target")
        success, msg = stop_process(target)
        await update.message.reply_text(msg)
        
    # E. CEO 감사 리포트 출력
    elif route.get("action") == "ceo_report":
        report = generate_ceo_report()
        await update.message.reply_text(report, parse_mode='Markdown')

    # D. Hermes 자가 치유 / 코드 수정 트리거 (Qwen3 분석 → Claude 수정 → 학습)
    elif route.get("action") == "hermes":
        query_text = user_query
        for prefix in ("/hermes ", "/수정 "):
            if query_text.startswith(prefix):
                query_text = query_text[len(prefix):]
                break

        status_msg = await update.message.reply_text(
            f"🔍 *[1단계] Qwen3 분석 중...*\n`{query_text[:100]}`",
            parse_mode="Markdown"
        )

        # ── 과거 학습 레슨 로드 (Qwen3 프롬프트에 주입)
        lessons = load_code_lessons()
        lessons_block = ""
        if lessons:
            recent_lessons = lessons[-5:]
            lessons_block = "\n\n## 과거 수정 사례 (참고):\n"
            for i, l in enumerate(recent_lessons, 1):
                used = "Claude" if l.get("used_claude") else "Qwen3 단독"
                lessons_block += f"{i}. [{used}] 문제: {l['problem'][:70]}\n   수정: {l['fix_summary'][:100]}\n"

        # ── Phase 1: Qwen3 분석 + 자신감 점수 요청
        analysis_prompt = (
            f"NutriStack 파이프라인 코드 수정 요청:\n{query_text}\n\n"
            f"다음을 분석하세요:\n"
            f"1. 문제 파일명 및 위치\n"
            f"2. 오류 원인\n"
            f"3. 수정 방법 (코드 포함)\n"
            f"4. 마지막 줄에 반드시: 자신감: X/10"
            f"{lessons_block}"
        )
        analysis = ask_ai(
            analysis_prompt,
            "당신은 Python 코드 디버깅 전문가입니다. NutriStack 자동화 파이프라인 구조를 숙지하고 있습니다.",
            MODEL_HERMES
        )

        # 자신감 점수 파싱
        conf_match = re.search(r'자신감[:\s]*(\d+)\s*/\s*10', analysis)
        confidence = int(conf_match.group(1)) if conf_match else 5
        logger.info(f"[Hernex] Qwen3 분석 자신감: {confidence}/10")

        env = os.environ.copy()
        env["OPENAI_API_KEY"] = "dummy"
        env["PYTHONIOENCODING"] = "utf-8"

        if confidence >= QWEN3_CONFIDENCE_THRESHOLD:
            # ── Qwen3 단독 처리 (학습 충분)
            await status_msg.edit_text(
                f"✅ *[Qwen3 자율 수정 — 자신감 {confidence}/10]*\n\n"
                f"```\n{analysis[:2000]}\n```",
                parse_mode="Markdown"
            )
            command = [
                "python", os.path.join("hermes-agent", "cli.py"),
                "--query", f"다음 분석 결과를 그대로 코드에 적용하세요:\n\n{analysis}",
                "--provider", "custom",
                "--base_url", "http://localhost:11434/v1",
                "--model", MODEL_HERMES
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.abspath("."), env=env
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
                output = stdout.decode("utf-8", errors="replace").strip()
                save_code_lesson(query_text, analysis, analysis, used_claude=False)
                mem["recent_events"].append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Qwen3 단독 코드 수정: {query_text[:60]}"
                )
                save_memory(mem)
                display = output[-2000:] if len(output) > 2000 else output
                await update.message.reply_text(
                    f"🟢 *Qwen3 단독 적용 완료*\n```\n{display}\n```",
                    parse_mode="Markdown"
                )
            except asyncio.TimeoutError:
                await update.message.reply_text("❌ Qwen3 적용 타임아웃 (180s)")
            except Exception as e:
                await update.message.reply_text(f"❌ 적용 오류: {e}")

        else:
            # ── Claude API 투입
            await status_msg.edit_text(
                f"🤖 *[2단계] Claude API 정밀 수정 중...*\n"
                f"Qwen3 자신감 {confidence}/10 — Claude 투입\n\n"
                f"Qwen3 분석:\n```\n{analysis[:600]}\n```",
                parse_mode="Markdown"
            )
            fix_prompt = (
                f"코드 수정 요청: {query_text}\n\n"
                f"Qwen3 분석 결과:\n{analysis}\n\n"
                f"위 분석을 검토하고 정확한 수정 코드를 작성하세요.\n"
                f"수정할 파일명, 수정 전 코드, 수정 후 코드를 명확히 구분해서 출력하세요."
            )
            claude_fix = ask_claude_code(
                fix_prompt,
                "당신은 Python 코드 수정 전문가입니다. 정확하고 안전한 수정만 제안하세요."
            )

            # Claude 수정안을 hermes-agent로 적용
            apply_prompt = f"다음 코드 수정안을 정확히 파일에 적용하세요:\n\n{claude_fix}"
            command = [
                "python", os.path.join("hermes-agent", "cli.py"),
                "--query", apply_prompt,
                "--provider", "custom",
                "--base_url", "http://localhost:11434/v1",
                "--model", MODEL_HERMES
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.abspath("."), env=env
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
                output = stdout.decode("utf-8", errors="replace").strip()
                save_code_lesson(query_text, analysis, claude_fix, used_claude=True)
                mem["recent_events"].append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Claude 코드 수정: {query_text[:60]}"
                )
                save_memory(mem)
                display_fix = claude_fix[:1500] if len(claude_fix) > 1500 else claude_fix
                await status_msg.edit_text(
                    f"✅ *[Claude 수정 완료]*\n\n```\n{display_fix}\n```",
                    parse_mode="Markdown"
                )
                if output:
                    display_out = output[-1000:] if len(output) > 1000 else output
                    await update.message.reply_text(
                        f"📝 적용 로그:\n```\n{display_out}\n```",
                        parse_mode="Markdown"
                    )
            except asyncio.TimeoutError:
                await update.message.reply_text("❌ 적용 타임아웃 (180s)")
            except Exception as e:
                logger.error(f"Hermes execution error: {e}")
                await status_msg.edit_text(f"❌ 수정 작업 오류: {e}")
            
    # E. 일반 대화 및 기억 피드백 (Connect AI 모델 직접 연동)
    else:
        status_msg = await update.message.reply_text("🤖 [Hernex] 생각 중...")
        
        memory_context = (
            f"마스터 취향: {mem.get('master_preference', '')}\n"
            f"블로그 구조: {mem.get('blog_structure', '')}\n"
            f"최근 이벤트 로그: {', '.join(mem.get('recent_events', [])[-5:])}\n"
        )
        
        system_prompt = (
            f"당신은 NutriStack Lab의 마스터를 보좌하는 수석 AI 비서 '헤넥스(Hernex)'입니다.\n"
            f"전문적이면서도 마스터님의 성향을 가장 먼저 고려해 답변해 주세요.\n\n"
            f"[마스터 영구 메모리(기억 장치)]\n{memory_context}"
        )
        
        response = ask_ai(user_query, system_prompt, MODEL_HERNEX)
        if not response:
            response = "❌ 로컬 Ollama 모델에 연결할 수 없거나 응답이 없습니다."
            
        if len(response) > 4000:
            response = response[:4000] + "\n\n..."
            
        await status_msg.edit_text(response)
        
        # 장기 기억 업데이트
        update_query = (
            f"유저 대화: {user_query}\n"
            f"AI의 대답: {response}\n\n"
            f"위 대화에서 마스터가 향후 지속적으로 적용하길 원하는 '새로운 규칙', '취향 선호도', '블로그 설정 관련 중요 팩트'가 있습니까? "
            f"있다면 장기 기억할 수 있도록 명확히 한 문장으로 요약해 주세요. "
            f"단순 잡담이거나 기억할 내용이 없다면 반드시 'PASS'라고만 응답하세요."
        )
        
        try:
            summary = ask_ai(update_query, "당신은 유용한 장기 기억 추출기입니다.", MODEL_HERNEX)
            if summary and "PASS" not in summary:
                mem["recent_events"].append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {summary.strip()}")
                
                # 성향 기억 자동 융합 업데이트
                preference_query = (
                    f"기존 마스터 취향 선호도: {mem['master_preference']}\n"
                    f"새로 감지된 정보: {summary.strip()}\n\n"
                    f"이 두 가지를 깔끔하게 통합하여 갱신할 새로운 '마스터 취향 선호도'를 한 문장으로 작성해 주세요."
                )
                updated_pref = ask_ai(preference_query, "정보 통합 전문가입니다.", MODEL_HERNEX)
                if updated_pref:
                    mem["master_preference"] = updated_pref.strip()
                save_memory(mem)
        except Exception as e:
            logger.error(f"Hernex auto-memory update failed: {e}")

# ── Blogger API ──────────────────────────────────────────────────────────────
def get_blogger_service():
    if not _GOOGLE_AVAILABLE or not TOKEN_FILE.exists():
        return None
    try:
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return _goog_build("blogger", "v3", credentials=creds)
    except Exception as e:
        logger.warning(f"Blogger API 연결 실패: {e}")
        return None


def _fetch_post(svc, post_id: str) -> dict | None:
    try:
        return svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
    except Exception:
        try:
            for status in ["LIVE", "SCHEDULED", "DRAFT"]:
                result = svc.posts().list(
                    blogId=BLOG_ID, status=status, maxResults=500
                ).execute()
                for p in result.get("items", []):
                    if p["id"] == post_id:
                        return p
        except Exception as e:
            logger.error(f"포스트 조회 실패: {e}")
    return None


def _sanitize_blogger_content(content: str) -> str:
    """
    orchestrator가 <!DOCTYPE html> 전체 문서를 포스트 content로 발행한 경우 복구:
    - SEO 블록 (DOCTYPE 이전) 유지
    - <style> 블록 추출 → 최상단으로 이동
    - <body> 내용만 추출
    - li:before CSS 제거 → TOC <li>에 → 직접 삽입
    - html.unescape로 이중인코딩 방지
    """
    import html as _html_lib

    # DOCTYPE 없으면 unescape만 적용
    doctype_pos = content.find('<!DOCTYPE')
    if doctype_pos == -1:
        doctype_pos = content.lower().find('<html')
    if doctype_pos == -1:
        return _html_lib.unescape(content)

    # SEO 블록 (DOCTYPE 이전)
    seo_block = content[:doctype_pos].strip()

    # <style> 블록 추출
    style_m = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL | re.IGNORECASE)
    style_content = ""
    if style_m:
        style_content = style_m.group(1)
        # li:before CSS 제거 (TOC에 → 직접 삽입)
        style_content = re.sub(r'\.toc\s+li::?before\s*\{[^}]*\}', '', style_content, flags=re.DOTALL)
        style_content = re.sub(r'\n{3,}', '\n\n', style_content)

    # <body> 이후 내용 추출
    body_pos = content.lower().find('<body')
    if body_pos != -1:
        body_tag_end = content.index('>', body_pos) + 1
        close = max(content.rfind('</body>'), content.rfind('</html>'))
        body_text = content[body_tag_end:close if close > body_tag_end else len(content)].strip()
    else:
        body_text = content[doctype_pos:]  # fallback: DOCTYPE부터 끝까지

    # TOC <li> → 직접 삽입
    def _fix_toc_li(toc_m):
        toc_html = toc_m.group(0)
        def _add_arrow(li_m):
            inner = li_m.group(1).strip()
            if inner.startswith(('→', '&#8594;', '&#x2192;')):
                return f'<li>{inner}</li>'
            return f'<li>→ {inner}</li>'
        return re.sub(r'<li>(.*?)</li>', _add_arrow, toc_html, flags=re.DOTALL)
    body_text = re.sub(r'<div[^>]+class="toc"[^>]*>.*?</div>', _fix_toc_li, body_text, flags=re.DOTALL)

    style_block = f'<style>\n{style_content}\n</style>\n' if style_content.strip() else ''
    cleaned = (seo_block + '\n' + style_block + body_text).strip()
    return _html_lib.unescape(cleaned)


def _update_post(svc, post_id: str, title: str, content: str, labels: list, is_scheduled: bool) -> bool:
    try:
        content = _sanitize_blogger_content(content)
        body = {"title": title, "content": content, "labels": labels}
        svc.posts().update(
            blogId=BLOG_ID, postId=post_id,
            body=body, publish=False
        ).execute()
        return True
    except Exception as e:
        logger.error(f"포스트 업데이트 실패: {e}")
        return False


# ── 카테고리별 자동 수정 로직 ─────────────────────────────────────────────────

def _fix_D2_internal_links(html: str, title: str) -> str:
    """내부 링크 2개 주입 (published_links.json 기반)"""
    if not PUBLISHED_LINKS.exists():
        return html
    try:
        links = json.loads(PUBLISHED_LINKS.read_text(encoding="utf-8"))
    except Exception:
        return html

    # 현재 포스트 제목에서 주요 키워드 추출
    stop = {"and","the","a","an","of","for","to","in","is","are","with","how",
            "when","what","why","does","do","my","i","me","its","vs","it"}
    kws = [w.lower() for w in re.findall(r'\b[A-Za-z]{4,}\b', title) if w.lower() not in stop]

    # 관련 포스트 찾기 (키워드 겹치는 순으로 정렬)
    candidates = []
    for lnk in links:
        lnk_title = lnk.get("title", "").lower()
        lnk_url   = lnk.get("url", "")
        if not lnk_url or title[:30].lower() in lnk_title:
            continue
        score = sum(1 for k in kws if k in lnk_title)
        if score > 0:
            candidates.append((score, lnk_url, lnk.get("title", "")))

    candidates.sort(reverse=True)
    chosen = candidates[:2]
    if not chosen:
        # 키워드 매칭 없으면 최신 2개
        chosen = [(0, lnk.get("url",""), lnk.get("title","")) for lnk in links[-2:] if lnk.get("url")]

    # disclosure 바로 앞 단락에 관련 글 링크 삽입
    link_block = '<p style="font-size:0.9em;color:#555;">Related reading: '
    link_parts = [f'<a href="{url}">{t[:50]}</a>' for _, url, t in chosen if url]
    link_block += " | ".join(link_parts) + "</p>"

    # disclosure div 바로 앞에 삽입
    if 'class="disclosure"' in html:
        html = html.replace('<div class="disclosure">', link_block + '\n<div class="disclosure">', 1)
    else:
        html += "\n" + link_block

    return html


def _fix_E1_ymyl(html: str) -> tuple[str, list]:
    """YMYL 위험 표현을 안전 표현으로 치환"""
    replacements = [
        (r'\bcure\b',           'support'),
        (r'\btreat\b',          'help with'),
        (r'\bdiagnose\b',       'identify'),
        (r'\bprescription\b',   'recommendation'),
        (r'\bguaranteed\b',     'may help'),
        (r'\bclinically proven\b', 'studied'),
        (r'will (cure|treat|prevent|eliminate|reverse)',
         lambda m: f'may help with'),
    ]
    changed = []
    for pattern, repl in replacements:
        new_html, n = re.subn(pattern, repl, html, flags=re.I)
        if n:
            changed.append(f"'{pattern}' → '{repl}' ({n}회)")
            html = new_html
    return html, changed


def _fix_B1_og_desc(html: str, title: str) -> str:
    """og:description 오염 시 Ollama로 재생성"""
    new_desc = ask_ai(
        f"Write a compelling meta description (120-155 characters) for a blog post titled:\n'{title}'\n"
        "Output only the description text. No quotes.",
        system_prompt="You are an SEO copywriter. Output only the meta description.",
        model=MODEL_HERMES
    ).strip()[:155]

    if not new_desc or len(new_desc) < 60:
        return html

    # og:description 교체
    html = re.sub(
        r'(<meta[^>]+property="og:description"[^>]+content=")[^"]*(")',
        lambda m: m.group(1) + new_desc + m.group(2),
        html, flags=re.I
    )
    # meta description 교체
    html = re.sub(
        r'(<meta[^>]+name="description"[^>]+content=")[^"]*(")',
        lambda m: m.group(1) + new_desc + m.group(2),
        html, flags=re.I
    )
    return html


def _fix_title(title: str, topic: str) -> str:
    """오염된 제목을 Ollama로 재생성. 같은 제목이 나오면 다른 각도로 재시도."""
    for attempt, angle in enumerate(["search-intent", "benefit-focused", "how-to"], 1):
        new_title = ask_ai(
            f"Write one SEO title for a blog post about '{topic}'.\n"
            f"Style: {angle}. Requirements: 40-65 chars, includes the nutrient name.\n"
            "No quotes, no punctuation at end.",
            system_prompt="You write SEO blog titles. Output only the title.",
            model=MODEL_HERMES
        ).strip()[:80]
        if len(new_title) >= 20 and new_title.lower() != title.lower():
            return new_title
    return title


# ── Hermes 큐 처리 핵심 함수 ──────────────────────────────────────────────────

async def process_hermes_queue(app) -> list:
    """
    hermes_queue.json의 pending 항목을 처리.
    수정 완료/실패 결과 목록 반환.
    """
    if not HERMES_QUEUE_FILE.exists():
        return []

    if not _acquire_queue_lock():
        logger.warning("Hermes 큐 lock 획득 실패 — 이번 poll 건너뜀")
        return []

    try:
        return await _process_hermes_queue_locked(app)
    finally:
        _release_queue_lock()


async def _process_hermes_queue_locked(app) -> list:
    """lock 획득 후 실제 큐 처리 (process_hermes_queue에서 호출)."""
    try:
        queue = json.loads(HERMES_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Hermes 큐 로드 실패: {e}")
        return []

    pending = [q for q in queue if q.get("status") == "pending"]
    if not pending:
        return []

    logger.info(f"[Hermes Queue] {len(pending)}개 항목 처리 시작")
    svc = get_blogger_service()
    results = []

    for item in pending:
        cat      = item.get("cat", "")
        post_id  = item.get("post_id", "")
        title    = item.get("title", "")
        note     = item.get("note", "")
        count    = item.get("count", 0)
        agent    = item.get("agent", "")

        # 알림 전용 카테고리
        if cat in NOTIFY_ONLY_CATS:
            msg = (
                f"⚠️ [Hermes 큐] 수동 수정 필요\n"
                f"카테고리: {cat} ({item.get('label','')})\n"
                f"포스트: {title}\n"
                f"문제: {note}\n"
                f"반복: {count}회\n"
                f"담당: {agent}"
            )
            item["status"] = "notified"
            results.append({"cat": cat, "title": title, "action": "notified", "msg": msg})
            logger.info(f"  [{cat}] 알림 전송: {title[:30]}")
            continue

        if cat not in AUTO_FIX_CATS:
            item["status"] = "skipped"
            results.append({"cat": cat, "title": title, "action": "skipped"})
            continue

        if not svc or not post_id:
            item["status"] = "failed"
            item["error"]  = "Blogger API 없음 또는 post_id 누락"
            results.append({"cat": cat, "title": title, "action": "failed"})
            continue

        # ── 재시도 횟수 추적
        retry_count = item.get("retry_count", 0) + 1
        item["retry_count"] = retry_count

        if retry_count > HERMES_MAX_RETRIES:
            item["status"] = "exhausted"
            msg = (f"[{cat}] {title[:40]} — "
                   f"{HERMES_MAX_RETRIES}회 시도 모두 실패, 수동 처리 필요")
            logger.warning(f"  [Hermes] exhausted: {msg}")
            results.append({"cat": cat, "title": title, "action": "exhausted", "msg": msg})
            continue

        # 포스트 가져오기
        post = _fetch_post(svc, post_id)
        if not post:
            item["status"] = "failed"
            item["error"]  = "포스트 조회 실패"
            results.append({"cat": cat, "title": title, "action": "failed",
                            "error": "포스트 조회 실패", "retry": retry_count})
            continue

        html    = post.get("content", "")
        p_title = post.get("title", title)
        labels  = post.get("labels", [])
        is_sched = post.get("status") == "SCHEDULED"
        changed  = []
        ok       = False

        try:
            if cat == "D2":
                new_html = _fix_D2_internal_links(html, p_title)
                if new_html != html:
                    ok = _update_post(svc, post_id, p_title, new_html, labels, is_sched)
                    changed.append(f"내부링크 2개 주입")

            elif cat == "E1":
                new_html, changes = _fix_E1_ymyl(html)
                if changes:
                    ok = _update_post(svc, post_id, p_title, new_html, labels, is_sched)
                    changed.extend(changes)

            elif cat == "B1":
                new_html = _fix_B1_og_desc(html, p_title)
                if new_html != html:
                    ok = _update_post(svc, post_id, p_title, new_html, labels, is_sched)
                    changed.append(f"og:description 재생성")

            elif cat in ("A1", "A2"):
                topic = re.sub(r'[^a-zA-Z0-9 ]', '', p_title)
                new_title = _fix_title(p_title, topic)
                if new_title != p_title:
                    ok = _update_post(svc, post_id, new_title, html, labels, is_sched)
                    changed.append(f"제목 교체: {p_title[:30]} → {new_title[:30]}")

        except Exception as e:
            logger.error(f"  [{cat}] 수정 중 오류 (시도 {retry_count}/{HERMES_MAX_RETRIES}): {e}")
            item["status"] = "failed"
            item["error"]  = str(e)
            results.append({"cat": cat, "title": title, "action": "failed",
                            "error": str(e), "retry": retry_count})
            continue

        if ok:
            item["status"]    = "done"
            item["fixed_at"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
            item["changes"]   = changed
            results.append({"cat": cat, "title": title, "action": "fixed", "changes": changed})
            logger.info(f"  [{cat}] 수정 완료: {title[:30]} — {changed}")
        else:
            item["status"] = "failed"
            item["error"]  = "수정 내용 없음 (HTML 변경 안 됨)"
            results.append({"cat": cat, "title": title, "action": "failed",
                            "error": "수정 내용 없음", "retry": retry_count})

    # 큐 저장 (atomic write)
    tmp = HERMES_QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, HERMES_QUEUE_FILE)
    return results


TIER1_ESCALATION_LOG = Path("20_Meta/tier1_escalation_log.json")
TIER1_THRESHOLD = 5  # 동일 카테고리 이 횟수 이상 반복 시 코드 수정 에스컬레이션


def _load_escalation_log() -> dict:
    if TIER1_ESCALATION_LOG.exists():
        try:
            return json.loads(TIER1_ESCALATION_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_escalation_log(log: dict):
    TIER1_ESCALATION_LOG.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def _auto_code_fix(app, chat_id: str, query: str, cat: str, count: int):
    """
    Tier 1 자동 코드 수정:
      Phase 1 — Qwen3(local) 분석 + 코드 수정안 작성
      Phase 2 — Claude API 검수 (APPROVED/REJECTED)
      Phase 3 — 승인 시 hermes-agent로 적용, 거부 시 알림
    """
    # ── Phase 1: Qwen3 분석 + 코드 수정안 작성 ───────────────────────────────
    lessons = load_code_lessons()
    lessons_block = ""
    if lessons:
        recent = [l for l in lessons[-10:] if cat in l.get("problem", "")]
        if recent:
            lessons_block = "\n\n참고 — 과거 유사 수정:\n"
            for l in recent[-3:]:
                lessons_block += f"- {l['fix_summary'][:100]}\n"

    fix_prompt = (
        f"[자동 에스컬레이션] 동일 문제 {count}회 반복:\n{query}\n\n"
        f"1. 원인 파일 및 위치\n"
        f"2. 왜 반복되는지\n"
        f"3. 정확한 코드 수정안 (파일명 / 수정 전 코드 / 수정 후 코드 명확히 구분)\n"
        f"4. 자신감: X/10{lessons_block}"
    )
    qwen3_fix = ask_ai(
        fix_prompt,
        "Python 코드 디버깅 전문가. NutriStack 자동화 파이프라인 구조 숙지.",
        MODEL_HERMES
    )

    conf_match = re.search(r'자신감[:\s]*(\d+)\s*/\s*10', qwen3_fix)
    confidence = int(conf_match.group(1)) if conf_match else 5
    logger.info(f"[1티어] Qwen3 수정안 작성 완료 — 자신감 {confidence}/10")

    # ── Phase 2: Claude API 검수 ──────────────────────────────────────────────
    review_prompt = (
        f"아래는 NutriStack 파이프라인 Python 코드 수정안입니다.\n"
        f"문제: {query}\n\n"
        f"Qwen3 수정안:\n{qwen3_fix}\n\n"
        f"이 수정안이 올바른지 검수하세요.\n"
        f"- 논리적 오류, 사이드이펙트, 누락된 케이스 점검\n"
        f"- 첫 줄에 반드시: APPROVED 또는 REJECTED\n"
        f"- 거부 시 구체적인 이유와 개선 방향 명시"
    )
    review = ask_claude_code(review_prompt, "Python 코드 검수 전문가. 정확성과 안전성 위주로 판단하세요.")
    approved = review.strip().upper().startswith("APPROVED")
    logger.info(f"[1티어] Claude 검수 결과: {'✅ APPROVED' if approved else '❌ REJECTED'}")

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy"
    env["PYTHONIOENCODING"] = "utf-8"

    if approved:
        # ── Phase 3: 승인 → hermes-agent로 적용 ─────────────────────────────
        apply_query = f"다음 코드 수정안을 정확히 파일에 적용하세요:\n\n{qwen3_fix}"
        command = [
            "python", os.path.join("hermes-agent", "cli.py"),
            "--query", apply_query,
            "--provider", "custom",
            "--base_url", "http://localhost:11434/v1",
            "--model", MODEL_HERMES
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.abspath("."), env=env
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            output = stdout.decode("utf-8", errors="replace").strip()
            save_code_lesson(query, qwen3_fix, qwen3_fix, used_claude=True)

            if chat_id:
                display = output[-1500:] if len(output) > 1500 else output
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔧 *[Tier 1 자동 수정 완료]*\n"
                        f"카테고리: `{cat}` ({count}회 반복)\n"
                        f"Qwen3 작성 → Claude 검수 ✅ APPROVED\n\n"
                        f"```\n{display}\n```"
                    ),
                    parse_mode="Markdown"
                )
        except asyncio.TimeoutError:
            logger.error(f"[1티어] {cat} 적용 타임아웃")
        except Exception as e:
            logger.error(f"[1티어] {cat} 적용 오류: {e}")

    else:
        # ── Phase 3: 거부 → Claude API가 직접 재수정 → hermes-agent 적용 ──────
        refix_prompt = (
            f"Qwen3의 수정안이 검수에서 거부됐습니다.\n"
            f"문제: {query}\n\n"
            f"Qwen3 수정안 (거부됨):\n{qwen3_fix}\n\n"
            f"검수 거부 사유:\n{review}\n\n"
            f"위 문제점을 반영해 올바른 코드 수정안을 작성하세요.\n"
            f"파일명 / 수정 전 코드 / 수정 후 코드를 명확히 구분해서 출력하세요."
        )
        claude_refix = ask_claude_code(refix_prompt, "Python 파이프라인 코드 수정 전문가.")
        apply_query = f"다음 코드 수정안을 정확히 파일에 적용하세요:\n\n{claude_refix}"
        command = [
            "python", os.path.join("hermes-agent", "cli.py"),
            "--query", apply_query,
            "--provider", "custom",
            "--base_url", "http://localhost:11434/v1",
            "--model", MODEL_HERMES
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.abspath("."), env=env
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            output = stdout.decode("utf-8", errors="replace").strip()
            save_code_lesson(query, qwen3_fix, claude_refix, used_claude=True)

            if chat_id:
                display = output[-1500:] if len(output) > 1500 else output
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔧 *[Tier 1 자동 수정 완료 — Claude 재수정]*\n"
                        f"카테고리: `{cat}` ({count}회 반복)\n"
                        f"Qwen3 작성 → Claude 검수 ❌ → Claude 재수정 → 적용\n\n"
                        f"```\n{display}\n```"
                    ),
                    parse_mode="Markdown"
                )
        except asyncio.TimeoutError:
            logger.error(f"[1티어] {cat} Claude 재수정 적용 타임아웃")
        except Exception as e:
            logger.error(f"[1티어] {cat} Claude 재수정 적용 오류: {e}")


async def check_tier1_escalation(app, chat_id: str):
    """hermes_queue 전체에서 동일 카테고리 5회 이상 반복 시 코드 수정 자동 트리거."""
    if not HERMES_QUEUE_FILE.exists():
        return

    try:
        queue = json.loads(HERMES_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    from collections import Counter
    cat_counts = Counter(item.get("cat", "") for item in queue if item.get("cat"))
    escalation_log = _load_escalation_log()
    triggered = False

    for cat, count in cat_counts.items():
        if count < TIER1_THRESHOLD:
            continue
        already_done = escalation_log.get(cat, {})
        # 마지막 에스컬레이션 이후 2건 이상 추가됐을 때만 재에스컬레이션
        last_count = already_done.get("count_at_escalation", 0)
        if count < last_count + 2:
            continue

        # 해당 cat 항목들의 문제 내용 수집
        cat_items = [item for item in queue if item.get("cat") == cat]
        notes = list({item.get("note", "") for item in cat_items if item.get("note")})[:5]
        query = (
            f"[{cat}] 품질 문제 {count}회 반복 감지.\n"
            f"반복 문제 패턴:\n" + "\n".join(f"- {n}" for n in notes) + "\n\n"
            f"이 문제가 반복되는 파이프라인 코드의 근본 원인을 찾아 수정하세요."
        )

        logger.warning(f"[1티어 에스컬레이션] {cat} {count}회 반복 → 자동 코드 수정 트리거")

        if chat_id:
            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🚨 *[1티어 자동 에스컬레이션]*\n"
                        f"`{cat}` 문제 *{count}회* 반복 감지\n"
                        f"근본 원인 코드 수정을 자동 실행합니다..."
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        await _auto_code_fix(app, chat_id, query, cat, count)

        escalation_log[cat] = {
            "count_at_escalation": count,
            "last_escalated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        _save_escalation_log(escalation_log)
        triggered = True

    if triggered:
        logger.info("[1티어] 에스컬레이션 완료")


async def hermes_queue_worker_tick(app):
    """job_queue 틱: 한 번 큐를 스캔하고 수정 결과를 Telegram으로 전송."""
    config  = load_config()
    chat_id = config.get("chat_id") if config else None

    results = []
    try:
        results = await process_hermes_queue(app)
    except Exception as e:
        logger.error(f"[Hermes Queue Worker] 처리 오류: {e}")

    if results and chat_id:
            fixed     = [r for r in results if r["action"] == "fixed"]
            notify    = [r for r in results if r["action"] == "notified"]
            failed    = [r for r in results if r["action"] == "failed"]
            exhausted = [r for r in results if r["action"] == "exhausted"]

            lines = ["🔧 **[Hermes 자동 수정 결과]**\n"]
            if fixed:
                lines.append(f"✅ 자동 수정 완료 ({len(fixed)}건):")
                for r in fixed:
                    changes_str = ", ".join(r.get("changes", []))
                    lines.append(f"  • [{r['cat']}] {r['title'][:40]}\n    → {changes_str}")
            if notify:
                lines.append(f"\n⚠️ 수동 확인 필요 ({len(notify)}건):")
                for r in notify:
                    lines.append(f"  • [{r['cat']}] {r['title'][:40]}")
            if failed:
                retry_info = lambda r: f" (시도 {r.get('retry','')}회)" if r.get('retry') else ""
                lines.append(f"\n❌ 수정 실패 ({len(failed)}건):")
                for r in failed:
                    lines.append(f"  • [{r['cat']}] {r['title'][:40]}{retry_info(r)} — {r.get('error','')}")
            if exhausted:
                lines.append(f"\n🚫 최대 재시도 초과 — 수동 처리 필요 ({len(exhausted)}건):")
                for r in exhausted:
                    lines.append(f"  • [{r['cat']}] {r['title'][:40]}\n    → {r.get('msg','')}")

            try:
                await app.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Telegram 알림 전송 실패: {e}")

    # ── 큐 처리 후 1티어 에스컬레이션 체크 (5회 이상 반복 카테고리 → 코드 자동 수정)
    try:
        await check_tier1_escalation(app, chat_id)
    except Exception as e:
        logger.error(f"[1티어 에스컬레이션 체크 오류] {e}")


def main():
    config = load_config()
    if not config or "bot_token" not in config:
        logger.error("telegram_config.json에 bot_token이 없습니다.")
        return

    application = ApplicationBuilder().token(config["bot_token"]).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ceo", ceo_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("audit", audit_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Hermes 큐 백그라운드 워커 등록
    application.job_queue.run_repeating(
        lambda ctx: asyncio.ensure_future(hermes_queue_worker_tick(ctx.application)),
        interval=HERMES_POLL_SEC,
        first=15,
        name="hermes_queue_worker",
    )

    logger.info(f"Hernex Agent가 기동되었습니다. Hermes 큐 감시 주기: {HERMES_POLL_SEC}초")
    application.run_polling()

if __name__ == '__main__':
    main()
