import os
import time
import json
import requests
import logging
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(__file__).parent
DRAFT_DIR = BASE_DIR / "10_Wiki" / "Projects" # 작가의 결과물(초안) 폴더
REVIEW_DIR = BASE_DIR / "10_Wiki" / "Decisions" # 검토 결과 및 결정 저장 폴더
PROMPT_DIR = BASE_DIR / "06_prompts"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "critic.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma4:e4b-it-q4_K_M"
REQUEST_TIMEOUT = 120
CRITIC_TEMPERATURE = 0.3 # 심사 및 검증을 위해 낮게 설정 (일관성 중요)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- [2. 유틸리티 함수] ---

def get_webhook_url():
    if not CONFIG_FILE.exists(): return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get("webhook_url")
    except Exception as e:
        logging.error(f"웹후크 읽기 실패: {e}")
        return None

def report_to_discord(status, topic, comment):
    url = get_webhook_url()
    if not url: return
    icon = "✅" if "승인" in status else "❌"
    payload = {"content": f"{icon} **[P-Reinforce Critic 심사 결과]**\n\n**주제:** {topic}\n**결과:** {status}\n**코멘트:** {comment[:400]}..."}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 수석 편집장입니다."

# --- [3. 크리틱 에이전트 핵심 로직] ---

def run_critic(topic, draft_data):
    """Gemma 2를 호출하여 블로그 초안을 심사합니다."""
    system_instruction = get_agent_prompt("05_Critic_Editor_In_Chief.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[블로그 초안 원고]:\n{draft_data}"
    
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "system": system_instruction,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.1,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "심사 보고서를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"심사 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def start_critic_mission():
    """작성된 초안을 찾아 편집장 심사를 수행합니다."""
    logging.info("🚀 크리틱 미션 가동...")
    
    # 필수 폴더 확인
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    
    # Draft_*.md 형식의 초안 검색
    draft_files = list(DRAFT_DIR.glob("Draft_*.md"))
    if not draft_files:
        logging.info("✅ 심사할 신규 초안이 없습니다.")
        return

    for d_file in draft_files:
        # 파일명 기반 토픽 추출 (Draft_토픽명.md)
        topic = d_file.stem.replace("Draft_", "")
        review_file = REVIEW_DIR / f"Review_{d_file.name}"
        
        # 중복 방지
        if review_file.exists():
            continue

        logging.info(f"⚖️ '{topic}' 초안에 대한 수석 편집장 심사 시작...")
        
        # 1. 초안 읽기
        try:
            with open(d_file, 'r', encoding='utf-8') as f:
                draft_content = f.read()
        except Exception as e:
            logging.error(f"초안 파일 읽기 실패: {e}")
            continue

        # 2. 브레인 가동 (심사 수행)
        logging.info("🧠 수석 편집장이 원고의 무결성과 톤앤매너를 심사 중입니다...")
        review_report = run_critic(topic, draft_content)
        
        # 3. 결과 저장
        try:
            with open(review_file, 'w', encoding='utf-8') as f:
                f.write(f"# Review Report: {topic}\n\n{review_report}\n\n---\n*Evaluated by Master Editor-in-Chief*")
            
            # 4. 발행 승인 여부 파악 (텍스트 파싱)
            status = "발행 승인 (APPROVED)" if "승인" in review_report or "APPROVED" in review_report.upper() else "발행 반려 (REJECTED)"
            
            logging.info(f"✅ 심사 완료: {review_file.name} [{status}]")
            report_to_discord(status, topic, review_report)
            
        except Exception as e:
            logging.error(f"심사 보고서 저장 실패: {e}")

if __name__ == "__main__":
    start_critic_mission()
