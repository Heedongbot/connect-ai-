import os
import time
import json
import requests
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(r"c:\Users\66683\OneDrive\바탕 화면\NutriStack_Lab\NutriStack_Lab")
RAW_DIR = BASE_DIR / "00_Raw"
WIKI_DIR = BASE_DIR / "10_Wiki" / "Projects"
DECISION_DIR = BASE_DIR / "10_Wiki" / "Decisions"
PROMPT_DIR = BASE_DIR / "06_prompts (AI에게 시킬 명령서 보관함)"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "automation.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "gemma2:9b"
FILE_READ_DELAY = 2  # 파일 작성 완료 대기 시간 (초)
REQUEST_TIMEOUT = 120 # AI 생성 타임아웃 (초)

# 로깅 설정: 파일과 콘솔에 동시에 기록
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- [2. 유틸리티 함수] ---

def pre_flight_check():
    """시스템 기동 전 Ollama 서버 및 모델 상태를 확인합니다."""
    logging.info("🔍 사전 시스템 점검 시작...")
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        response.raise_for_status()
        models = [m['name'] for m in response.json().get('models', [])]
        
        if DEFAULT_MODEL not in models and f"{DEFAULT_MODEL}:latest" not in models:
            logging.warning(f"⚠️ 경고: '{DEFAULT_MODEL}' 모델이 Ollama에 설치되어 있지 않습니다.")
            logging.info(f"현재 설치된 모델: {models}")
        else:
            logging.info(f"✅ Ollama 연결 성공 및 '{DEFAULT_MODEL}' 모델 확인됨.")
            
    except Exception as e:
        logging.error(f"❌ Ollama 서버 연결 실패: {e}")
        logging.error("Ollama가 실행 중인지 확인하십시오 (http://localhost:11434)")

def get_webhook_url():
    """discord_webhook.json에서 URL을 안전하게 가져옵니다."""
    if not CONFIG_FILE.exists():
        logging.warning(f"⚠️ 설정 파일 없음: {CONFIG_FILE}")
        return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get("webhook_url")
    except Exception as e:
        logging.error(f"❌ 웹후크 설정 읽기 실패: {e}")
        return None

def report_to_discord(agent_name, content):
    """지정된 에이전트 이름으로 디스코드에 보고합니다."""
    url = get_webhook_url()
    if not url: return
    
    payload = {"content": f"🚀 **[{agent_name}]**\n{content}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"📡 디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    """06_prompts 폴더에서 에이전트 명령서를 읽어옵니다."""
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    logging.error(f"❌ 프롬프트 파일 없음: {path}")
    return "당신은 NutriStack의 전문 에이전트입니다."

# --- [3. 에이전트 핵심 로직] ---

def run_ai_agent(prompt, system_instruction):
    """Ollama API를 호출하여 AI 응답을 생성합니다."""
    combined_prompt = f"{system_instruction}\n\n[USER DATA]\n{prompt}"
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "응답을 생성하지 못했습니다.")
    except requests.exceptions.RequestException as e:
        err_msg = f"AI 호출 중 네트워크 오류 발생: {e}"
        logging.error(err_msg)
        return err_msg

# --- [4. 이벤트 핸들러] ---

class NutriStackHandler(FileSystemEventHandler):
    """00_Raw 폴더를 감시하고 신규 파일 발생 시 처리합니다."""
    
    def on_created(self, event):
        if event.is_directory: return
        
        file_path = Path(event.src_path)
        if file_path.suffix.lower() not in ['.txt', '.md']: return
        
        logging.info(f"📂 신규 파일 포착: {file_path.name}")
        time.sleep(FILE_READ_DELAY) # 파일 쓰기 완료 대기
        
        self.process_file(file_path)

    def process_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if not content.strip():
                logging.warning(f"⚠️ 빈 파일 무시됨: {file_path.name}")
                return

            # 1단계: 플래너 분석
            planner_prompt = get_agent_prompt("01_Planner_P_Reinforce.md")
            logging.info(f"🧠 '{file_path.name}' 분석을 위해 플래너 에이전트 가동...")
            
            result = run_ai_agent(content, planner_prompt)
            
            # 2단계: 결과 저장 (Wiki 및 Decision)
            self.save_results(file_path, result)
            
            # 3단계: 디스코드 보고
            report_to_discord("P-Reinforce Planner", 
                             f"분석 완료: `{file_path.name}`\n\n**[핵심 요약]**\n{result[:400]}...")
            
            logging.info(f"✅ 처리가 완료되었습니다: {file_path.name}")
            
        except Exception as e:
            logging.error(f"❌ '{file_path.name}' 처리 중 치명적 오류: {e}")
            report_to_discord("System Error", f"파일 처리 중 오류 발생: `{file_path.name}`\n{e}")

    def save_results(self, source_path, result):
        """분석 결과를 파일로 저장합니다."""
        # Wiki 리포트 저장
        wiki_file = WIKI_DIR / f"Plan_{source_path.stem}.md"
        with open(wiki_file, 'w', encoding='utf-8') as f:
            f.write(f"# {source_path.stem} 분석 리포트\n\n{result}")
        
        # 의사결정 로그 저장 (신규 Decision 로직)
        dec_file = DECISION_DIR / f"{time.strftime('%Y%m%d')}_{source_path.stem}.md"
        with open(dec_file, 'w', encoding='utf-8') as f:
            f.write(f"# Decision Reason: {source_path.stem}\n\n{result[:1000]}\n\n---\n*Source: {source_path}*")

# --- [5. 메인 루프] ---

if __name__ == "__main__":
    # 사전 점검
    pre_flight_check()
    
    # 필수 폴더 재생성 확인 (안전장치)
    for d in [RAW_DIR, WIKI_DIR, DECISION_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(NutriStackHandler(), str(RAW_DIR), recursive=True)
    observer.start()
    
    logging.info(f"🛰️ 사령부 가동 중... 감시 폴더: {RAW_DIR}")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("🛑 시스템이 안전하게 종료되었습니다.")
    
    observer.join()
