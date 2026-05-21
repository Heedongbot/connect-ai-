import os
import time
import json
import requests
import logging
from pathlib import Path
from duckduckgo_search import DDGS

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(__file__).parent
WIKI_DIR = BASE_DIR / "10_Wiki" / "Projects"
RESEARCH_DIR = BASE_DIR / "10_Wiki" / "Topics"
PROMPT_DIR = BASE_DIR / "06_prompts"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "researcher.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma4:e4b-it-q8_0"
REQUEST_TIMEOUT = 180 # 리서치는 더 긴 시간이 소요될 수 있음
SEARCH_MAX_RESULTS = 5

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
    payload = {"content": f"🔬 **[{agent_name}]**\n{content}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 전문 연구원입니다."

# --- [3. 도구: 인터넷 검색] ---

def search_web(query):
    """DuckDuckGo를 통해 실시간 데이터를 수집합니다."""
    logging.info(f"🌐 인터넷 검색 시도: {query}")
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=SEARCH_MAX_RESULTS):
                results.append(f"제목: {r['title']}\n내용: {r['body']}\n링크: {r['href']}\n")
        return "\n".join(results)
    except Exception as e:
        logging.error(f"검색 중 오류 발생: {e}")
        return f"인터넷 검색 데이터를 가져오는 데 실패했습니다: {e}"

# --- [4. 에이전트 핵심 로직] ---

def run_researcher(topic, search_data):
    """Gemma 2를 호출하여 연구 리포트를 생성합니다."""
    system_instruction = get_agent_prompt("02_Researcher_Synergy.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[인터넷 검색 데이터]:\n{search_data}"
    
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
        return response.json().get('response', "분석 결과를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"연구 분석 중 오류 발생: {e}"

# --- [5. 미션 실행기] ---

def start_research_mission():
    """아직 연구되지 않은 플랜을 찾아 리서치를 수행합니다."""
    logging.info("🚀 리서치 미션 시작...")
    
    # 필수 폴더 확인
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    
    plans = list(WIKI_DIR.glob("Plan_*.md"))
    if not plans:
        logging.info("✅ 연구할 신규 계획서가 없습니다.")
        return

    for plan_file in plans:
        # 파일명 기반 토픽 추출
        topic = plan_file.stem.replace("Plan_", "")
        research_file = RESEARCH_DIR / f"Research_{topic}.md"
        
        # 중복 방지
        if research_file.exists():
            continue

        logging.info(f"🧪 '{topic}' 연구 미션 수행 중...")
        
        # 1. 계획서 내용 확인 (참조용)
        # with open(plan_file, 'r', encoding='utf-8') as f:
        #    plan_content = f.read()

        # 2. 검색 수행
        search_query = f"{topic} health benefits scientific research synergy stacking"
        search_results = search_web(search_query)
        
        # 3. 브레인 가동
        logging.info("🧠 AI 연구원이 데이터를 분석하고 시너지 스택을 도출합니다...")
        report = run_researcher(topic, search_results)
        
        # 4. 결과 저장
        try:
            with open(research_file, 'w', encoding='utf-8') as f:
                f.write(f"# Research Report: {topic}\n\n{report}\n\n---\n## [Raw Search Data]\n{search_results}")
            
            logging.info(f"✅ 연구 완료: {research_file.name}")
            report_to_discord("Researcher Agent", 
                             f"'{topic}'에 대한 심층 연구가 완료되었습니다.\n과학적 근거와 시너지 스택이 `10_Wiki/Topics`에 저장되었습니다.")
        except Exception as e:
            logging.error(f"결과 저장 실패: {e}")

if __name__ == "__main__":
    start_research_mission()
