import os
import time
import json
import requests
import logging
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(r"c:\Users\66683\OneDrive\바탕 화면\NutriStack_Lab\NutriStack_Lab")
PROJECT_DIR = BASE_DIR / "10_Wiki" / "Projects" # 모든 결과물이 모이는 곳
PROMPT_DIR = BASE_DIR / "06_prompts (AI에게 시킬 명령서 보관함)"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "formatter_auditor.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma2:9b"
REQUEST_TIMEOUT = 300
FORMATTER_TEMPERATURE = 0.2 # 정확성과 구조적 무결성을 위해 낮게 설정

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

def report_to_discord(topic, format_report):
    url = get_webhook_url()
    if not url: return
    payload = {"content": f"🛠️ **[P-Reinforce 최종 포맷팅 완료]**\n\n**주제:** {topic}\n**검수 결과 요약:** {format_report[:400]}..."}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 최종 포맷터이자 문법 전문가입니다."

# --- [3. 포맷터 에이전트 핵심 로직] ---

def run_formatter(topic, final_content, visual_info):
    """Gemma 2를 호출하여 최종 원고와 비주얼 정보를 결합한 배포용 코드를 생성합니다."""
    system_instruction = get_agent_prompt("08_Formatter_Auditor.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[최종 원고]:\n{final_content}\n\n[비주얼 정보(이미지 프롬프트 등)]:\n{visual_info}"
    
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "system": system_instruction,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": FORMATTER_TEMPERATURE,
            "top_p": 0.9,
            "num_predict": 4096
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "최종 포맷팅 결과를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"포맷팅 작업 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def run_formatter_mission():
    """브랜드 리파이닝까지 마친 최종 원고와 비주얼 리포트를 결합하여 Ready용 파일을 생성합니다."""
    logging.info("🚀 최종 포맷터 & 오디터 미션 가동...")
    
    # Final_*.md 형식의 최종 원고 검색
    final_files = list(PROJECT_DIR.glob("Final_*.md"))
    if not final_files:
        logging.info("✅ 포맷팅할 신규 최종 원고가 없습니다.")
        return

    for f_file in final_files:
        # 토픽 추출
        topic_stem = f_file.stem
        clean_topic = topic_stem.replace("Final_", "").replace("SEO_", "").replace("Draft_", "")
        publish_file = PROJECT_DIR / f"Ready_{topic_stem}.md"
        
        # 중복 방지
        if publish_file.exists():
            continue

        logging.info(f"🛠️ '{clean_topic}' 원고와 비주얼 에셋을 결합하여 게시용 코드로 변환 중...")
        
        # 1. 최종 원고 읽기
        try:
            with open(f_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logging.error(f"원고 파일 읽기 실패: {e}")
            continue

        # 2. 대응하는 비주얼 리포트 검색
        visual_file = PROJECT_DIR / f"Visual_{topic_stem}.md"
        visual_info = "이미지 정보 없음 (텍스트 전용 포스팅으로 처리)"
        if visual_file.exists():
            try:
                with open(visual_file, 'r', encoding='utf-8') as v:
                    visual_info = v.read()
            except Exception as e:
                logging.error(f"비주얼 파일 읽기 실패: {e}")

        # 3. 브레인 가동 (포맷팅 및 검수 수행)
        logging.info("🧠 포맷터가 시맨틱 HTML 구조를 설계하고 문법을 최종 점검 중입니다...")
        formatted_result = run_formatter(clean_topic, content, visual_info)
        
        # 4. 결과 저장
        try:
            with open(publish_file, 'w', encoding='utf-8') as p:
                p.write(f"# Ready to Publish: {clean_topic}\n\n{formatted_result}\n\n---\n*Verified by HTML/MD Structure Auditor*")
            
            logging.info(f"✅ 최종 배포용 파일 생성 완료: {publish_file.name}")
            report_to_discord(clean_topic, formatted_result)
            
        except Exception as e:
            logging.error(f"최종본 저장 실패: {e}")

if __name__ == "__main__":
    run_formatter_mission()
