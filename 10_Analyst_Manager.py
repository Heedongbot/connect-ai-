import os
import time
import json
import requests
import logging
from pathlib import Path
from datetime import datetime

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(__file__).parent
META_DIR = BASE_DIR / "20_Meta"
POLICY_FILE = META_DIR / "Policy.md"      # 시스템 지휘 지침(가중치) 기록 파일
FEEDBACK_FILE = META_DIR / "Feedback.md"  # 마스터의 피드백 입력 파일
PROMPT_DIR = BASE_DIR / "06_prompts"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "analyst_rl_manager.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:14b-instruct-q4_K_M"
REQUEST_TIMEOUT = 180

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

def report_to_discord(analysis_report):
    url = get_webhook_url()
    if not url: return
    payload = {"content": f"📊 **[P-Reinforce 시스템 진화 보고]**\n\n{analysis_report[:1500]}..."}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 데이터 분석가이자 강화 학습 매니저입니다."

# --- [3. 애널리스트 에이전트 핵심 로직] ---

def run_analyst(current_policy, master_feedback, performance_data):
    """Gemma 2를 호출하여 데이터를 분석하고 시스템 진화 가이드를 생성합니다."""
    system_instruction = get_agent_prompt("10_Analyst_RL_Manager.md")
    combined_prompt = (
        f"### [현재 시스템 정책]\n{current_policy}\n\n"
        f"### [마스터의 피드백]\n{master_feedback}\n\n"
        f"### [콘텐츠 성과 데이터]\n{performance_data}"
    )
    
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "system": system_instruction,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.4,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "진화 지침을 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"성과 분석 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def run_analyst_mission():
    """성과 데이터와 피드백을 바탕으로 시스템을 진화시킵니다."""
    logging.info("📊 애널리스트 강화 학습(RL) 루프 기동...")
    
    # 필수 폴더/파일 초기화
    META_DIR.mkdir(parents=True, exist_ok=True)
    if not FEEDBACK_FILE.exists():
        with open(FEEDBACK_FILE, 'w', encoding='utf-8') as f:
            f.write("# Human Feedback Storage\n\n(여기에 마스터님의 피드백을 입력해 주세요. 예: '더 감성적인 어조가 필요함', 'Reward: +1.0')")

    # 1. 기존 데이터 로드
    current_policy = ""
    if POLICY_FILE.exists():
        try:
            with open(POLICY_FILE, 'r', encoding='utf-8') as f:
                current_policy = f.read()
        except Exception as e:
            logging.error(f"정책 파일 읽기 실패: {e}")

    master_feedback = ""
    try:
        with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
            master_feedback = f.read()
    except Exception as e:
        logging.error(f"피드백 파일 읽기 실패: {e}")

    # 2. 성과 데이터 수집 (시뮬레이션 혹은 외부 API 연동 가능)
    # 실제 운영 시 Google Analytics API 또는 Search Console API 등과 연동 가능
    performance_data_summary = "최근 포스팅 'NMN 시너지' 조회수 500회, 클릭률 5.2% 달성. '마그네슘' 대비 20% 상승."

    # 3. 브레인 가동 (분석 및 진화 지휘)
    logging.info("🧠 애널리스트가 보상($R$) 데이터를 기반으로 시스템 진화를 설계 중입니다...")
    analysis_report = run_analyst(current_policy, master_feedback, performance_data_summary)
    
    # 4. 새로운 정책 저장 (지식의 진화 기록)
    try:
        updated_content = f"# System Evolution Policy (Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n{analysis_report}"
        with open(POLICY_FILE, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        logging.info(f"✅ 시스템 정책(Policy.md) 업데이트 성공.")
        report_to_discord(analysis_report)
        
    except Exception as e:
        logging.error(f"정책 파일 저장 실패: {e}")

if __name__ == "__main__":
    run_analyst_mission()
