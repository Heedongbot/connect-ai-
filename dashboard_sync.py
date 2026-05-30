import json
import os
from pathlib import Path
from datetime import datetime

# 경로 설정
BASE_DIR = Path(__file__).parent
META_DIR = BASE_DIR / "20_Meta"
DASHBOARD_DIR = BASE_DIR / "dashboard"
DATA_FILE = DASHBOARD_DIR / "data.js"

def sync():
    """실제 DB 파일을 읽어 대시보드용 JS 데이터 파일 생성"""
    try:
        # 1. 총 게시물 수 확인
        links_file = META_DIR / "published_links.json"
        total_posts = 0
        if links_file.exists():
            links = json.loads(links_file.read_text(encoding='utf-8-sig'))
            total_posts = len(links)

        # 2. 평균 점수 계산
        perf_file = META_DIR / "performance_db.json"
        avg_score = 0.0
        if perf_file.exists():
            perf = json.loads(perf_file.read_text(encoding='utf-8-sig'))
            if perf:
                scores = [p.get("score", 0) for p in perf if "score" in p]
                if scores:
                    # 점수가 0~1 사이면 100점으로 환산, 이미 100점대면 그대로 사용
                    raw_avg = sum(scores) / len(scores)
                    avg_score = raw_avg * 10 if raw_avg <= 1.0 else raw_avg / 10

        # 3. 자가 수리 횟수
        self_repaired = 0
        if perf_file.exists():
            perf = json.loads(perf_file.read_text(encoding='utf-8-sig'))
            self_repaired = sum(1 for p in perf if "[REWRITE]" in p.get("issues", ""))

        # 4. 실시간 로그 읽기
        real_logs = []
        log_files = [BASE_DIR / "orchestrator.log", BASE_DIR / "autonomous_ceo.log"]
        for lf in log_files:
            if lf.exists():
                lines = lf.read_text(encoding='utf-8-sig').splitlines()
                # 최근 10줄씩 가져와서 파일명 태그 달기
                tag = "[ORCH]" if "orchestrator" in lf.name else "[CEO]"
                for line in lines[-15:]:
                    if "[" in line and "]" in line: # 유효한 로그 형태만
                        real_logs.append(f"{tag} {line}")
        
        # 시간순 정렬 (로그 시작의 타임스탬프 기준)
        real_logs.sort(reverse=True) # 최신이 위로
        real_logs = [l.replace('"',"'") for l in real_logs[:20]] # JSON 안전하게 처리

        # 5. 에이전트 실시간 상태 추적 (체크포인트 감시)
        agent_status = {
            "researcher": "대기 중",
            "writer": "대기 중",
            "critic": "대기 중",
            "ceo": "비즈니스 관리 중"
        }
        current_mission = {
            "title": "현재 진행 중인 미션 없음",
            "step": "Standby",
            "progress": 0
        }
        
        cp_dir = BASE_DIR / "02_Checkpoints"
        active_cps = list(cp_dir.glob("*.json"))
        if active_cps:
            try:
                latest_cp = max(active_cps, key=lambda p: p.stat().st_mtime)
                
                # ★ 핵심: 체크포인트가 10분 이상 수정 안 되었으면 완료된 작업으로 간주
                cp_age = (datetime.now() - datetime.fromtimestamp(latest_cp.stat().st_mtime)).total_seconds()
                if cp_age > 600:  # 10분 이과 = 옥데이트 아닔
                    pass  # 대기 상태 유지
                else:
                    ctx = json.loads(latest_cp.read_text(encoding='utf-8-sig'))
                    
                    # 미션 제목 추출
                    topic = ctx.get("topic", latest_cp.stem.replace('_',' '))
                    current_mission["title"] = topic
                    critic_retries = ctx.get("critic_retries", 0)

                    if "research" not in ctx:
                        agent_status["researcher"] = "PubMed 논문 분석 중..."
                        current_mission["step"] = "Step 1: Researching"
                        current_mission["progress"] = 20
                    elif critic_retries > 0 and len(ctx.get("sections", {})) < 5:
                        agent_status["critic"] = f"피드백 각인 후 재작성 중 ({critic_retries}/3)..."
                        agent_status["writer"] = f"크리틱 피드백 반영 중..."
                        current_mission["step"] = f"Critic Retry {critic_retries}/3"
                        current_mission["progress"] = 75
                    elif len(ctx.get("sections", {})) < 5:
                        done = len(ctx.get('sections', {}))
                        agent_status["writer"] = f"본문 섹션 작성 중 ({done}/5)..."
                        current_mission["step"] = f"Step 2: Section Writing ({done}/5)"
                        current_mission["progress"] = 30 + (done * 10)
                    elif "hook" not in ctx:
                        agent_status["persona"] = "노르딕 후크 작성 중..."
                        current_mission["step"] = "Step 4: Hook Writing"
                        current_mission["progress"] = 60
                    elif "title" not in ctx:
                        agent_status["seo"] = "SEO 타이틀 생성 중..."
                        current_mission["step"] = "Step 5: SEO Title"
                        current_mission["progress"] = 70
                    elif "images" not in ctx:
                        agent_status["visual"] = "이미지 프롬프트 설계 중..."
                        current_mission["step"] = "Step 3: Image Design"
                        current_mission["progress"] = 55
                    else:
                        agent_status["critic"] = "최종 원고 정밀 검수 중..."
                        current_mission["step"] = "Step 9: Quality Audit"
                        current_mission["progress"] = 85
            except: pass

        # CEO 상태는 로그 기반으로 더 디테일하게
        if any("감사 결과" in l for l in real_logs[:5]):
            agent_status["ceo"] = "과거 포스팅 감사 및 교정 중..."

        # 6. JS 파일로 쓰기 (CORS 문제 방지)
        js_content = f"""
const REAL_DATA = {{
    totalPosts: {total_posts},
    avgScore: {avg_score:.1f},
    selfRepaired: {self_repaired},
    logs: {json.dumps(real_logs, ensure_ascii=False)},
    agentStatus: {json.dumps(agent_status, ensure_ascii=False)},
    currentMission: {json.dumps(current_mission, ensure_ascii=False)},
    lastUpdate: "{datetime.now().strftime('%H:%M:%S')}"
}};
"""
        DATA_FILE.write_text(js_content, encoding='utf-8-sig')
        # print(f"  📊 대시보드 데이터 동기화 완료: {total_posts}개 포스팅")

    except Exception as e:
        print(f"  ❌ 대시보드 동기화 실패: {e}")

if __name__ == "__main__":
    sync()
