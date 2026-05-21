import os
import time
import json
import requests
import logging
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(__file__).parent
DRAFT_DIR = BASE_DIR / "10_Wiki" / "Projects" # 분석 및 최적화가 완료된 파일들이 위치한 폴더
PROMPT_DIR = BASE_DIR / "06_prompts"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "persona_guardian.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:14b-instruct-q4_K_M"
REQUEST_TIMEOUT = 300 # 리파이닝 작업은 긴 글을 처리하므로 타임아웃 넉넉히 설정
PERSONA_TEMPERATURE = 0.8 # 감성적인 표현과 문체 리듬을 위해 높게 설정

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

def report_to_discord(topic, persona_feedback):
    url = get_webhook_url()
    if not url: return
    payload = {"content": f"✨ **[P-Reinforce 페르소나 리파이닝 완료]**\n\n**주제:** {topic}\n**피드백:** {persona_feedback[:400]}..."}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 브랜드 가디언입니다."

# --- [3. 페르소나 에이전트 핵심 로직] ---

def run_persona_refiner(topic, content):
    """Gemma 2를 호출하여 원고에 브랜드 페르소나와 감성적 터치를 입힙니다."""
    system_instruction = get_agent_prompt("06_Persona_Guardian.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[처리할 원고 본문]:\n{content}"
    
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "system": system_instruction,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.6,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "문체 리파이닝 결과를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"페르소나 리파이닝 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def run_persona_mission():
    """최적화된 원고를 찾아 브랜드 페르소나를 입히고 최종본(Final)을 생성합니다."""
    logging.info("🚀 페르소나 가디언 미션 가동...")
    
    # 1. SEO 최적화된 파일(SEO_*.md)을 우선 타겟으로 하고, 없으면 Draft_*.md 검색
    target_files = list(DRAFT_DIR.glob("SEO_*.md"))
    if not target_files:
        logging.info("SEO 최적화 파일을 찾지 못해 일반 초안(Draft_*)을 검색합니다.")
        target_files = list(DRAFT_DIR.glob("Draft_*.md"))
        
    if not target_files:
        logging.info("✅ 다듬을 신규 원고가 없습니다.")
        return

    for t_file in target_files:
        # 파일명 분석 및 토픽 추출
        topic = t_file.stem
        # 접두사 제거 로직 (SEO_Draft_... 등 복합 접두사 대응)
        clean_topic = topic.replace("SEO_Draft_", "").replace("Draft_", "")
        final_file = DRAFT_DIR / f"Final_{topic}.md"
        
        # 중복 방지
        if final_file.exists():
            continue

        logging.info(f"✨ '{clean_topic}' 원고에 브랜드의 생명력을 불어넣는 중...")
        
        # 1. 대상 원고 읽기
        try:
            with open(t_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logging.error(f"파일 읽기 실패: {e}")
            continue

        # 2. 브레인 가동 (페르소나 리파이닝 수행)
        logging.info("🧠 브랜드 가디언이 문장을 인간적이고 따뜻하게 다듬고 있습니다...")
        polished_result = run_persona_refiner(clean_topic, content)
        
        # 3. 결과 저장
        try:
            with open(final_file, 'w', encoding='utf-8') as f:
                f.write(f"# Final Manuscript: {clean_topic}\n\n{polished_result}\n\n---\n*Refined by Tone & Empathy Guardian*")
            
            logging.info(f"✅ 페르소나 리파이닝 완료: {final_file.name}")
            report_to_discord(clean_topic, polished_result)
            
        except Exception as e:
            logging.error(f"최종본 저장 실패: {e}")

if __name__ == "__main__":
    run_persona_mission()
