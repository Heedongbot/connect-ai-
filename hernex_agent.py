import os
import re
import json
import logging
import asyncio
import psutil
import subprocess
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from master_hq import ask_ai

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
    "orchestrator": {"file": "00_NutriStack_Grand_Orchestrator_v5.py", "name": "오케스트레이터"},
    "scheduler": {"file": "daily_scheduler_v5.py", "name": "데일리 스케줄러"},
    "discord": {"file": "bot_start.py", "name": "디스코드 봇"},
    "ceo": {"file": "00_NutriStack_Autonomous_CEO_v1.py", "name": "Autonomous CEO"}
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
        "- 특정 프로세스 시작/기동: START:프로세스명 (프로세스명: orchestrator, scheduler, discord, ceo, all)\n"
        "- 특정 프로세스 종료: STOP:프로세스명 (프로세스명: orchestrator, scheduler, discord, ceo)\n"
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
            for t in ["orchestrator", "scheduler", "discord", "ceo"]:
                if t in class_res.lower():
                    target = t
                    break
            route = {"action": "start", "target": target}
        elif "STOP" in class_res:
            target = "orchestrator"
            for t in ["orchestrator", "scheduler", "discord", "ceo"]:
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

    # D. Hermes 자가 치유 / 코드 수정 트리거
    elif route.get("action") == "hermes":
        query_text = user_query
        if query_text.startswith("/hermes "):
            query_text = query_text[8:]
        elif query_text.startswith("/수정 "):
            query_text = query_text[4:]
            
        status_msg = await update.message.reply_text(f"🛠️ [Hernex - Hermes Engine] 코드/스킬 자가 치유 작업에 착수합니다...\n명령: {query_text}")
        
        command = [
            "python",
            os.path.join("hermes-agent", "cli.py"),
            "--query", query_text,
            "--provider", "custom", 
            "--base_url", "http://localhost:11434/v1",
            "--model", MODEL_HERMES
        ]
        
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = "dummy"
        
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.abspath("."),
                env=env
            )
            stdout, stderr = await process.communicate()
            output = stdout.decode('utf-8', errors='replace').strip()
            err_output = stderr.decode('utf-8', errors='replace').strip()
            
            if len(output) > 3000:
                display_output = "...(중략)...\n" + output[-3000:]
            else:
                display_output = output
                
            final_msg = f"✅ *Hernex 스킬 자동화 수정 완료*\n\n```text\n{display_output}\n```"
            if process.returncode != 0:
                final_msg += f"\n\n⚠️ *경고/에러 로그:*\n```text\n{err_output[-500:]}\n```"
                
            await status_msg.edit_text(final_msg, parse_mode='Markdown')
            
            # 영구 메모리 기록
            mem["recent_events"].append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 코드 자가치유 실행: {query_text}")
            save_memory(mem)
        except Exception as e:
            logger.error(f"Hermes execution error: {e}")
            await status_msg.edit_text(f"❌ Hernex 수정 작업 오류: {str(e)}")
            
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
    
    logger.info("Hernex Agent가 기동되었습니다. 메시지 대기 중...")
    application.run_polling()

if __name__ == '__main__':
    main()
