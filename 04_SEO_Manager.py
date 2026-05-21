import os
import time
import json
import requests
import logging
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(__file__).parent
DRAFT_DIR = BASE_DIR / "10_Wiki" / "Projects" # 작가가 작성한 초안 폴더
PROMPT_DIR = BASE_DIR / "06_prompts"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "seo_optimizer.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:14b-instruct-q4_K_M"
REQUEST_TIMEOUT = 120
SEO_TEMPERATURE = 0.4 # 알고리즘적 일관성을 유지하며 약간의 창의성 발휘

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

def report_to_discord(topic, seo_summary):
    url = get_webhook_url()
    if not url: return
    payload = {"content": f"📈 **[P-Reinforce SEO 최적화 완료]**\n\n**주제:** {topic}\n**SEO 분석 요약:** {seo_summary[:400]}..."}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 검색 엔진 최적화 전문가입니다."

# --- [3. SEO 에이전트 핵심 로직] ---

def run_seo_optimizer(topic, draft_data):
    """Gemma 2를 호출하여 블로그 초안의 SEO 분석 및 구조화를 수행합니다."""
    system_instruction = get_agent_prompt("04_SEO_Optimizer.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[블로그 원고]:\n{draft_data}"
    
    data = {
        "model": DEFAULT_MODEL,
        "prompt": combined_prompt,
        "system": system_instruction,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.2,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', "SEO 분석 결과를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"SEO 최적화 분석 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def start_seo_mission():
    """작성된 초안을 찾아 검색 엔진 최적화 분석을 수행합니다."""
    logging.info("🚀 SEO 최적화 미션 가동...")
    
    # Draft_*.md 형식의 초안 검색
    draft_files = list(DRAFT_DIR.glob("Draft_*.md"))
    if not draft_files:
        logging.info("✅ 최적화할 신규 초안이 없습니다.")
        return

    for d_file in draft_files:
        # 파일명 기반 토픽 추출
        topic = d_file.stem.replace("Draft_", "")
        seo_report_file = DRAFT_DIR / f"SEO_{d_file.name}"
        
        # 중복 방지
        if seo_report_file.exists():
            continue

        logging.info(f"📈 '{topic}' 초안에 대한 검색 엔진 최적화(SEO) 분석 시작...")
        
        # 1. 초안 읽기
        try:
            with open(d_file, 'r', encoding='utf-8') as f:
                draft_content = f.read()
        except Exception as e:
            logging.error(f"초안 파일 읽기 실패: {e}")
            continue

        # 2. 브레인 가동 (SEO 분석 수행)
        logging.info("🧠 SEO 전문가가 구글 알고리즘에 맞춰 원고 구조를 분석 중입니다...")
        seo_report = run_seo_optimizer(topic, draft_content)
        
        # 3. 결과 저장
        try:
            with open(seo_report_file, 'w', encoding='utf-8') as f:
                f.write(f"# SEO Optimization Report: {topic}\n\n{seo_report}\n\n---\n*Analyzed by Semantic Optimizer*")
            
            logging.info(f"✅ SEO 최적화 완료: {seo_report_file.name}")
            report_to_discord(topic, seo_report)
            
        except Exception as e:
            logging.error(f"SEO 리포트 저장 실패: {e}")

if __name__ == "__main__":
    start_seo_mission()
