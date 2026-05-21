import os
import time
import json
import requests
import logging
from pathlib import Path

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(r"c:\Users\66683\OneDrive\바탕 화면\NutriStack_Lab\NutriStack_Lab")
FINAL_DIR = BASE_DIR / "10_Wiki" / "Projects" # 페르소나 작업이 완료된 최종 원고 폴더
PROMPT_DIR = BASE_DIR / "06_prompts (AI에게 시킬 명령서 보관함)"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "visual_architect.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma2:9b"
REQUEST_TIMEOUT = 120
VISUAL_TEMPERATURE = 0.6 # 창의성과 기술적 지표의 균형

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

def report_to_discord(topic, visual_plan):
    url = get_webhook_url()
    if not url: return
    payload = {"content": f"🎨 **[P-Reinforce 비주얼 설계 완료]**\n\n**주제:** {topic}\n**이미지 전략 요약:** {visual_plan[:400]}..."}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 비주얼 아키텍트입니다."

# --- [3. 비주얼 에이전트 핵심 로직] ---

def run_visual_architect(topic, final_content):
    """Gemma 2를 호출하여 원고 기반의 이미지 컨셉 및 SD 프롬프트를 설계합니다."""
    system_instruction = get_agent_prompt("07_Visual_Architect.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[최종 원고 본문]:\n{final_content}"
    
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
        return response.json().get('response', "비주얼 설계 결과를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"비주얼 설계 중 오류 발생: {e}"

# --- [4. 미션 실행기] ---

def run_visual_mission():
    """최종 원고를 찾아 시각적 자산(이미지 프롬프트 등)을 설계합니다."""
    logging.info("🚀 비주얼 아키텍트 미션 가동...")
    
    # Final_*.md 형식의 최종 원고 검색
    final_files = list(FINAL_DIR.glob("Final_*.md"))
    if not final_files:
        logging.info("✅ 시각화할 신규 최종 원고가 없습니다.")
        return

    for f_file in final_files:
        # 파일명 분석 및 토픽 추출
        topic = f_file.stem
        # 접두사 정리 (Final_SEO_Draft_... 대응)
        clean_topic = topic.replace("Final_", "").replace("SEO_", "").replace("Draft_", "")
        visual_file = FINAL_DIR / f"Visual_{topic}.md"
        
        # 중복 방지
        if visual_file.exists():
            continue

        logging.info(f"🎨 '{clean_topic}' 원고를 위한 비주얼 에셋 설계 중...")
        
        # 1. 최종 원고 읽기
        try:
            with open(f_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logging.error(f"원고 파일 읽기 실패: {e}")
            continue

        # 2. 브레인 가동 (비주얼 설계 수행)
        logging.info("🧠 비주얼 아키텍트가 독창적인 이미지 컨셉과 SD 프롬프트를 생성 중입니다...")
        visual_plan = run_visual_architect(clean_topic, content)
        
        # 3. 결과 저장
        try:
            with open(visual_file, 'w', encoding='utf-8') as f:
                f.write(f"# Visual Design Plan: {clean_topic}\n\n{visual_plan}\n\n---\n*Designed by Visual Architect (SD Engineer)*")
            
            logging.info(f"✅ 비주얼 설계 완료: {visual_file.name}")
            report_to_discord(clean_topic, visual_plan)
            
        except Exception as e:
            logging.error(f"비주얼 설계서 저장 실패: {e}")

if __name__ == "__main__":
    run_visual_mission()
