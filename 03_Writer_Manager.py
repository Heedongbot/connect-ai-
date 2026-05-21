import os
import time
import json
import requests
import logging
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(__file__).parent
TOPIC_DIR = BASE_DIR / "10_Wiki" / "Topics"    # 리서처의 결과물(연구 데이터) 폴더
DRAFT_DIR = BASE_DIR / "10_Wiki" / "Projects" # 작가의 결과물(초안) 저장 폴더
PROMPT_DIR = BASE_DIR / "06_prompts"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "writer.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:14b-instruct-q4_K_M"
REQUEST_TIMEOUT = 300 # 작문은 긴 시간이 소요되므로 충분히 설정
OUTPUT_TOKEN_LIMIT = 4096 # 긴 글 작성을 위한 출력 토큰 제한
WRITER_TEMPERATURE = 0.7  # 창의적인 작문을 위한 온도 설정

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

def report_to_discord(agent_name, content):
    url = get_webhook_url()
    if not url: return
    payload = {"content": f"✍️ **[{agent_name}]**\n{content}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 전문 작가입니다."

# --- [3. 작가 에이전트 핵심 로직] ---

def run_writer(topic, research_data):
    """Gemma 2를 호출하여 심도 있는 블로그 포스팅 초안을 작성합니다."""
    system_instruction = get_agent_prompt("03_Writer_Gardener.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[연구 리서치 데이터]:\n{research_data}"
    
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "system": system_instruction,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "num_predict": OUTPUT_TOKEN_LIMIT,
            "temperature": 0.6,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "초안을 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"집필 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def start_writer_mission():
    """리서치가 완료된 주제를 찾아 블로그 포스팅 작성을 시작합니다."""
    logging.info("🚀 작가 미션 가동...")
    
    # 필수 폴더 확인
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Research_*.md 형식의 리서치 결과물 검색
    research_files = list(TOPIC_DIR.glob("Research_*.md"))
    if not research_files:
        logging.info("✅ 새로 집필할 연구 리포트가 없습니다.")
        return

    for res_file in research_files:
        # 파일명 기반 토픽 추출 (Research_토픽명.md)
        topic = res_file.stem.replace("Research_", "")
        draft_file = DRAFT_DIR / f"Draft_{topic}.md"
        
        # 중복 방지
        if draft_file.exists():
            continue

        logging.info(f"📝 '{topic}' 주제로 블로그 포스팅 집필 시작...")
        
        # 1. 연구 데이터 읽기
        try:
            with open(res_file, 'r', encoding='utf-8') as f:
                research_content = f.read()
        except Exception as e:
            logging.error(f"리서치 파일 읽기 실패: {e}")
            continue

        # 2. 브레인 가동 (집필 수행)
        logging.info("🧠 지식 정원사가 원고를 정성껏 작성 중입니다... (1,500단어 이상 목표)")
        blog_post = run_writer(topic, research_content)
        
        # 3. 결과 저장
        try:
            with open(draft_file, 'w', encoding='utf-8') as f:
                f.write(f"--- \nStatus: Draft\nTopic: {topic}\nAgent: Writer V21 (Gardener)\n--- \n\n{blog_post}")
            
            logging.info(f"✅ 집필 완료: {draft_file.name}")
            report_to_discord("Writer Agent", 
                             f"'{topic}'에 대한 블로그 초안 집필이 완료되었습니다.\n친근한 전문가 어조와 시너지 스택이 포함된 원고가 `10_Wiki/Projects`에 저장되었습니다.")
        except Exception as e:
            logging.error(f"원고 저장 실패: {e}")

if __name__ == "__main__":
    start_writer_mission()
