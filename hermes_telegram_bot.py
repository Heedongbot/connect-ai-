import os
import json
import logging
import asyncio
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Connect AI의 로컬 Ollama 연동 함수 가져오기
from master_hq import ask_ai

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

CONFIG_FILE = "telegram_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 *Hermes 수석 엔지니어 봇에 오신 것을 환영합니다!*\n\n"
        "저는 Connect AI(오케스트레이터)의 코드를 분석하고 수정하는 개발자입니다.\n"
        "코드 수정, 기능 추가, 에러 원인 분석 등 어떤 작업이든 지시해 주시면 처리하겠습니다."
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text
    
    # 1. Hermes 전용 명령어 처리 (스킬 자동화 및 메모리 관리용)
    if user_query.lower().startswith("/hermes "):
        query = user_query[8:].strip()
        status_msg = await update.message.reply_text(f"🛠️ [Hermes] 명령 수신. 스킬 및 메모리 작업 착수...\n명령: {query}")
        
        command = [
            "python",
            os.path.join("hermes-agent", "cli.py"),
            "--query", query,
            "--provider", "custom", 
            "--base_url", "http://localhost:11434/v1",
            "--model", "qwen3:14b-q4_K_M"
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
                
            final_msg = f"✅ *Hermes 작업 완료*\n\n```text\n{display_output}\n```"
            if process.returncode != 0:
                final_msg += f"\n\n⚠️ *경고/에러 로그:*\n```text\n{err_output[-500:]}\n```"
                
            await status_msg.edit_text(final_msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error running Hermes: {e}")
            await status_msg.edit_text(f"❌ Hermes 작업 중 오류 발생: {str(e)}")
            
    # 2. 일반 대화 (Connect AI - Ollama 직접 연동)
    else:
        status_msg = await update.message.reply_text("🤖 [Connect AI] 마스터의 질문에 답변을 생성 중입니다...")
        
        system_prompt = "당신은 NutriStack Lab의 마스터를 보좌하는 수석 AI 비서입니다. 친절하고 전문적으로 답변하세요. 텔레그램을 통해 답변하므로 마크다운을 적절히 사용하세요."
        # ask_ai 함수 내부에서 agent_memory.txt를 읽어 자동으로 주입함
        response = ask_ai(user_query, system_prompt, "qwen3:14b-q4_K_M", agent_name="Telegram Assistant")
        
        if not response:
            response = "❌ 로컬 Ollama(qwen3) 모델에 연결할 수 없거나 응답이 없습니다."
            
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Hermes 텔레그램 봇이 시작되었습니다. 메시지 대기 중...")
    application.run_polling()

if __name__ == '__main__':
    main()
