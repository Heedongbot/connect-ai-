import os
import json
import asyncio
import logging
import requests
import subprocess
import sys
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BASE_DIR       = Path(__file__).parent
ROOT_DIR       = BASE_DIR.parent
CONFIG_FILE    = BASE_DIR / "telegram_config.json"
WATCHDOG_PAUSE = ROOT_DIR / "queue" / "watchdog.pause"
PIPELINE_LOCK  = ROOT_DIR / "queue" / "pipeline.lock"
ORCH_SCRIPT    = BASE_DIR / "00_NutriStack_Grand_Orchestrator_v5.py"
OLLAMA_URL     = "http://localhost:11434/api/chat"
OLLAMA_CHAT_MODEL = "qwen2:7b-instruct-q4_0"   # 일반 대화용 (가벼움)
OLLAMA_AGENT_MODEL = "qwen3:14b-q4_K_M"         # /hermes 코드 작업용 (강력)


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"설정 로드 실패: {e}")
        return None


def _ollama_chat(message: str) -> str:
    """Ollama API 직접 호출 (동기). 스레드 executor에서 실행됨."""
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_CHAT_MODEL,
            "messages": [{"role": "user", "content": message}],
            "stream": False
        }, timeout=120)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "응답 없음")
    except requests.Timeout:
        return "❌ Ollama 응답 타임아웃 (120s)"
    except Exception as e:
        return f"❌ Ollama 오류: {e}"


# ── 파이프라인 유틸 ──────────────────────────────────────────────
def _find_orch_pid():
    """오케스트레이터 PID 반환. 없으면 None."""
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "Grand_Orchestrator" in line:
                parts = line.strip().split()
                return int(parts[-1])
    except Exception:
        pass
    return None

def _kill_orch():
    pid = _find_orch_pid()
    if pid:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        return pid
    return None

def _get_last_log_lines(n=5):
    log = BASE_DIR / "orchestrator.log"
    if not log.exists():
        return "로그 없음"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "로그 읽기 실패"

def _get_today_schedule():
    """topic_bank.json에서 오늘 스케줄 읽기.
    - 오늘 completed_at이 있는 항목 (이미 발행됨)
    - pending 상태에서 time이 오늘 아직 남은 항목 (예정)
    """
    import datetime as dt
    topic_bank = BASE_DIR / "20_Meta" / "topic_bank.json"
    if not topic_bank.exists():
        return "topic_bank.json 없음"
    try:
        data = json.loads(topic_bank.read_text(encoding="utf-8"))
        today = dt.date.today().strftime("%Y-%m-%d")
        now_time = dt.datetime.now().strftime("%H:%M")

        today_items = []
        for x in data:
            completed_at = x.get("completed_at", "")
            status = x.get("status", "pending")
            # 오늘 발행 완료된 것
            if completed_at.startswith(today):
                today_items.append(x)
            # 아직 pending이고 오늘 예정된 시간이 남은 것
            elif status == "pending" and x.get("time", "") >= now_time:
                today_items.append(x)

        if not today_items:
            return f"오늘({today}) 남은 예정 포스팅 없음"

        lines = []
        for x in sorted(today_items, key=lambda x: x.get("completed_at") or x.get("time", "")):
            status = x.get("status", "pending")
            icon = "✅" if status == "completed" else ("⏭️" if status == "skipped" else "⏳")
            time_str = x.get("completed_at", "")[:5] if status == "completed" else x.get("time", "")
            lines.append(f"{icon} {time_str} {x.get('topic', '')}")

        done = sum(1 for x in today_items if x.get("status") == "completed")
        return f"📅 오늘 스케줄 ({done}/{len(today_items)} 완료)\n\n" + "\n".join(lines)
    except Exception as e:
        return f"스케줄 읽기 실패: {e}"


def _get_credits():
    """(잔여잔액, 총사용액) 튜플 반환. 실패 시 (None, None)."""
    try:
        f = BASE_DIR / "20_Meta" / "claude_credits.json"
        usage = BASE_DIR / "20_Meta" / "api_usage_log.json"
        if not f.exists(): return None, None
        cr = json.loads(f.read_text(encoding="utf-8"))
        baseline   = float(cr.get("balance_at_update", 0))
        total_used = float(cr.get("total_used", 0))
        date = cr.get("last_updated", "")
        # last_updated 당일은 이미 콘솔 잔액에 반영 → 다음날부터 차감 (이중차감 방지)
        spent = 0.0
        if usage.exists():
            data = json.loads(usage.read_text(encoding="utf-8"))
            spent = sum(v.get("cost_usd", 0) for k, v in data.items() if k > date)
        remaining    = round(max(baseline - spent, 0), 2)
        total_used_now = round(total_used + spent, 2)
        return remaining, total_used_now
    except Exception:
        return None, None


# ── 봇 명령어 ────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *NutriStack 파이프라인 봇*\n\n"
        "📋 *파이프라인 제어:*\n"
        "`/status` — 전체 상태 확인 (오케스트레이터·크레딧·로그)\n"
        "`/stop` — 오케스트레이터 중지 + 워치독 일시정지\n"
        "`/resume` — 워치독 재활성화 → 자동 재시작\n"
        "`/restart` — 오케스트레이터 강제 재시작\n\n"
        "🛠️ *기타:*\n"
        "`!스케줄` — 오늘 발행 일정 확인\n"
        "`/hermes 명령` → 코드 작업 (파일 수정 등)\n"
        "`/help` — 이 명령어 목록 보기\n"
        "일반 메시지 → Ollama 대화",
        parse_mode="Markdown"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ollama + 오케스트레이터 + 크레딧 상태 확인."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        ollama_status = f"✅ 실행 중 | {', '.join(models[:3])}"
    except Exception:
        ollama_status = "❌ 응답 없음"

    pid = _find_orch_pid()
    orch_status = f"✅ 실행 중 (PID {pid})" if pid else "❌ 정지됨"
    watchdog_status = "⏸️ 일시정지" if WATCHDOG_PAUSE.exists() else "✅ 활성"
    lock_status = "🔒 잠김" if PIPELINE_LOCK.exists() else "🔓 없음"

    last_log = _get_last_log_lines(3)

    await update.message.reply_text(
        f"*시스템 상태*\n\n"
        f"🦙 Ollama: {ollama_status}\n"
        f"⚙️ 오케스트레이터: {orch_status}\n"
        f"🐕 워치독: {watchdog_status}\n"
        f"🔒 파이프라인 락: {lock_status}\n\n"
        f"📋 *최근 로그:*\n```\n{last_log}\n```",
        parse_mode="Markdown"
    )


async def pipeline_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """워치독 일시정지 + 오케스트레이터 종료."""
    WATCHDOG_PAUSE.parent.mkdir(parents=True, exist_ok=True)
    WATCHDOG_PAUSE.touch()
    pid = _kill_orch()
    if pid:
        await update.message.reply_text(
            f"⏸️ *파이프라인 중지 완료*\n\n"
            f"• 오케스트레이터 종료 (PID {pid})\n"
            f"• 워치독 일시정지 (watchdog.pause 생성)\n\n"
            f"재시작하려면 `/resume`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"⏸️ *워치독 일시정지 완료*\n\n"
            f"• 오케스트레이터가 이미 정지됨\n"
            f"• 워치독 일시정지 (watchdog.pause 생성)\n\n"
            f"재시작하려면 `/resume`",
            parse_mode="Markdown"
        )


async def pipeline_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """워치독 재활성화 → 자동으로 오케스트레이터 재시작."""
    if WATCHDOG_PAUSE.exists():
        WATCHDOG_PAUSE.unlink()
        await update.message.reply_text(
            "▶️ *워치독 재활성화 완료*\n\n"
            "watchdog.pause 삭제됨 — 워치독이 60초 내로 오케스트레이터를 재시작합니다.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "ℹ️ 워치독이 이미 활성 상태입니다.\n"
            "오케스트레이터가 실행 중이 아니라면 60초 내로 자동 재시작됩니다."
        )


async def pipeline_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """오케스트레이터 강제 재시작 (워치독이 자동으로 살림)."""
    if WATCHDOG_PAUSE.exists():
        WATCHDOG_PAUSE.unlink()
    pid = _kill_orch()
    if pid:
        await update.message.reply_text(
            f"🔄 *재시작 중...*\n\n"
            f"• 오케스트레이터 종료 (PID {pid})\n"
            f"• 워치독이 60초 내로 자동 재시작합니다.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🔄 *재시작 요청 완료*\n\n"
            "오케스트레이터가 이미 정지 상태입니다.\n"
            "워치독이 60초 내로 자동 시작합니다.",
            parse_mode="Markdown"
        )


HELP_TEXT = """
🤖 *NutriStack 명령어 가이드*

━━━━━━━━━━━━━━━━━
📡 *[Hermes] 파이프라인 제어*
━━━━━━━━━━━━━━━━━
`/status` — Ollama·오케스트레이터 실행 상태
`/stop` — 파이프라인 완전 중지 (워치독 포함)
`/resume` — 중지된 파이프라인 재시작
`/restart` — 오케스트레이터만 강제 재시작

━━━━━━━━━━━━━━━━━
🧠 *[Hernex] 블로그 관리*
━━━━━━━━━━━━━━━━━
`/ceo` — 블로그 품질·통계 현황 리포트
`/approve [키워드]` — 대기 중인 글 승인 발행
  예) `/approve vitamin c`
`/audit [URL]` — 특정 글 품질 감사
  예) `/audit https://www.nutristacklab.com/...`

━━━━━━━━━━━━━━━━━
🎮 *[Discord] 원격 제어*
━━━━━━━━━━━━━━━━━
📊 *현황*
`!현황` — 전체 발행 현황
`!오늘` — 오늘 발행된 포스팅
`!대기` — 승인 대기 목록
`!status` — 프로세스 생존 확인

✅ *승인/폐기*
`!승인 [주제명]` — 포스팅 승인
`!폐기 [주제명]` — 포스팅 폐기

⚡ *수동 제어*
`!trigger [주제명]` — 포스팅 즉시 트리거
`!지시 [주제]` — 새 주제 직접 지시

🔄 *재시작*
`!restart_all` — 전체 프로세스 재시작
`!restart scheduler` — 스케줄러만
`!restart orchestrator` — 오케스트레이터만
`!restart hernex_agent` — 자동수정 봇만
`!restart morning_report` — 아침보고 봇만

🤖 *에이전트*
`!호출 [에이전트명] [질문]` — 에이전트 직접 호출
`!보고 [주제]` — 발행 보고 생성

━━━━━━━━━━━━━━━━━
📋 *[메시지] 단축 명령*
━━━━━━━━━━━━━━━━━
`!명령어` — 이 도움말 보기
`!스케줄` — 오늘 발행 일정 확인
`/hermes [작업]` — Hermes AI 코드 작업 요청
  예) `/hermes 오케스트레이터 로그 요약해줘`
"""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text

    # !명령어 → 전체 명령어 가이드
    if user_query.strip() in ("!명령어", "!help", "!도움말", "!commands"):
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    # !스케줄 → 오늘 topic_bank 일정 조회
    if user_query.strip() in ("!스케줄", "!schedule"):
        await update.message.reply_text(_get_today_schedule())
        return

    # /hermes 명령 → Hermes Agent CLI 실행 (파일 수정, 코드 작업 등)
    if user_query.lower().startswith("/hermes "):
        query = user_query[8:].strip()
        status_msg = await update.message.reply_text(f"🛠️ Hermes 작업 중...\n`{query}`", parse_mode="Markdown")

        hermes_cli = BASE_DIR / "hermes-agent" / "cli.py"
        command = [
            "python", str(hermes_cli),
            "--query", query,
            "--provider", "ollama",
            "--base_url", "http://localhost:11434/v1",
            "--model", OLLAMA_AGENT_MODEL
        ]
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = "dummy"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(BASE_DIR),
                env=env
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output:
                output = stderr.decode("utf-8", errors="replace").strip() or "출력 없음"
            if len(output) > 3500:
                output = "...(중략)...\n" + output[-3500:]
            await status_msg.edit_text(f"✅ *Hermes 완료*\n\n```\n{output}\n```", parse_mode="Markdown")
        except asyncio.TimeoutError:
            await status_msg.edit_text("❌ Hermes 타임아웃 (180s)")
        except Exception as e:
            await status_msg.edit_text(f"❌ 오류: {e}")

    # 일반 대화 → Ollama 직접 호출
    else:
        status_msg = await update.message.reply_text("💭 생각 중...")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _ollama_chat, user_query)
        if len(response) > 4000:
            response = response[:4000] + "\n\n...(길이 제한으로 생략됨)"
        await status_msg.edit_text(response)


def main():
    config = load_config()
    if not config or "bot_token" not in config:
        logger.error("telegram_config.json에 bot_token이 없습니다.")
        return

    application = ApplicationBuilder().token(config["bot_token"]).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stop", pipeline_stop))
    application.add_handler(CommandHandler("resume", pipeline_resume))
    application.add_handler(CommandHandler("restart", pipeline_restart))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Hermes 텔레그램 봇 시작. 메시지 대기 중...")
    application.run_polling()


if __name__ == "__main__":
    main()
