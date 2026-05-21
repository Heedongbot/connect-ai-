import os
import time
import json
import requests
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# --- [1. 전역 설정 및 상수] ---
BASE_DIR = Path(r"c:\Users\66683\OneDrive\바탕 화면\NutriStack_Lab\NutriStack_Lab")
READY_DIR = BASE_DIR / "10_Wiki" / "Projects" # 포맷팅 완료된 배포 대기 폴더
PROMPT_DIR = BASE_DIR / "06_prompts (AI에게 시킬 명령서 보관함)"
CONFIG_FILE = BASE_DIR / "discord_webhook.json"
LOG_FILE = BASE_DIR / "deployment_engineer.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma2:9b"
REQUEST_TIMEOUT = 120

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

def report_to_discord(topic, status, git_status):
    url = get_webhook_url()
    if not url: return
    icon = "🚀" if "완료" in status else "⚠️"
    payload = {"content": f"{icon} **[P-Reinforce 최종 배포 보고]**\n\n**주제:** {topic}\n**배포 상태:** {status}\n**Git 상태:** {git_status}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"디스코드 전송 실패: {e}")

def get_agent_prompt(filename):
    path = PROMPT_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return "당신은 NutriStack의 시스템 자동화 엔지니어입니다."

# --- [3. 도구: Git 자동화] ---

def git_commit_and_push(message):
    """변경 사항을 Git 저장소에 기록합니다."""
    logging.info(f"💾 Git 백업 시작: {message}")
    try:
        # 현재 작업 디렉토리를 프로젝트 루트로 변경하여 실행
        # (subprocess.run의 cwnd 매개변수 사용 권장)
        subprocess.run(["git", "add", "."], check=True, cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", message], check=True, cwd=BASE_DIR)
        # subprocess.run(["git", "push"], check=True, cwd=BASE_DIR) # 원격 저장소 필요 시 활성화
        return "✅ Git 커밋 성공"
    except subprocess.CalledProcessError as e:
        return f"❌ Git 오류 (변경 사항 없음 또는 설정 미비): {e}"
    except Exception as e:
        return f"❌ Git 예외 발생: {e}"

# --- [4. 엔지니어 에이전트 핵심 로직] ---

def run_automation_engineer(topic, ready_content):
    """Gemma 2를 호출하여 최종 결과물의 기술적 무결성을 검수합니다."""
    system_instruction = get_agent_prompt("09_Automation_Engineer.md")
    combined_prompt = f"[TOPIC]: {topic}\n\n[최종 배포용 원고]:\n{ready_content}"
    
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
        return response.json().get('response', "검수 결과를 생성하지 못했습니다.")
    except Exception as e:
        logging.error(f"Ollama 호출 실패: {e}")
        return f"기술 검수 중 오류 발생: {e}"

# --- [5. 미션 실행기] ---

def run_deployment_mission():
    """배포 준비 완료된 원고를 찾아 기술 검수 후 최종 배포(시뮬레이션) 및 Git 백업을 수행합니다."""
    logging.info("🚀 자동화 엔지니어 배포 미션 가동...")
    
    # Ready_*.md 형식의 배포 대기 파일 검색
    ready_files = list(READY_DIR.glob("Ready_*.md"))
    if not ready_files:
        logging.info("✅ 배포할 신규 파일이 없습니다.")
        return

    for r_file in ready_files:
        # 파일명 기반 토픽 추출
        topic_stem = r_file.stem
        clean_topic = topic_stem.replace("Ready_", "").replace("Final_", "").replace("SEO_", "").replace("Draft_", "")
        
        logging.info(f"🚀 '{clean_topic}' 배포 공정 시작...")
        
        # 1. 원고 읽기
        try:
            with open(r_file, 'r', encoding='utf-8') as f:
                ready_content = f.read()
        except Exception as e:
            logging.error(f"파일 읽기 실패: {e}")
            continue

        # 2. 브레인 가동 (기술 검수 수행)
        logging.info("🧠 엔지니어가 기술적 무결성(HTML/Asset)을 검토 중입니다...")
        tech_report = run_automation_engineer(clean_topic, ready_content)
        
        # 3. 배포 결정 및 실행
        if "Pass" in tech_report or "성공" in tech_report:
            logging.info("✔️ 기술 검수 통과! 최종 배포 및 백업을 진행합니다.")
            
            # [시뮬레이션] Blogger/WordPress API 호출
            publish_status = "Blogger 발행 완료 (API 시뮬레이션)"
            
            # 4. Git 백업 (지식 저장소 영구 보존)
            git_msg = f"Reinforced Knowledge: {clean_topic} ({datetime.now().strftime('%Y-%m-%d')})"
            git_res = git_commit_and_push(git_msg)
            
            # 5. 디스코드 최종 보고
            report_to_discord(clean_topic, publish_status, git_res)
            
            # 처리 완료 후 파일 이름 변경 (중복 실행 방지)
            try:
                done_file = READY_DIR / f"Done_{r_file.name}"
                r_file.rename(done_file)
                logging.info(f"🎊 모든 공정 완료: {done_file.name}")
            except Exception as e:
                logging.error(f"파일 상태 변경 실패: {e}")
        else:
            logging.warning(f"⚠️ 기술 검수 실패: {clean_topic}. 수동 확인이 필요합니다.")
            report_to_discord(clean_topic, "배포 실패 (기술 결함 발견)", "N/A (검수 실패)")

if __name__ == "__main__":
    run_deployment_mission()
