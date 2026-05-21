// NutriStack Lab - Dashboard Controller

document.addEventListener('DOMContentLoaded', () => {
    // 1. 시간 업데이트
    const timeDisplay = document.getElementById('current-time');
    setInterval(() => {
        const now = new Date();
        timeDisplay.textContent = now.toTimeString().split(' ')[0];
    }, 1000);

    // 2. 실제 데이터 및 에이전트 상태 반영
    function updateStats() {
        if (typeof REAL_DATA !== 'undefined') {
            const statsValues = document.querySelectorAll('.stat-item .value');
            if (statsValues.length >= 3) {
                statsValues[0].textContent = REAL_DATA.totalPosts;
                statsValues[1].textContent = REAL_DATA.avgScore;
                statsValues[2].textContent = REAL_DATA.selfRepaired;
            }

            // 11인 에이전트 말풍선 실시간 연동
            if (REAL_DATA.agentStatus) {
                const s = REAL_DATA.agentStatus;
                const progress = REAL_DATA.currentMission ? REAL_DATA.currentMission.progress : 0;

                const agentMap = [
                    // [CSS 클래스,           활성 조건,        활성 멘트,                  비활성 멘트]
                    ['planner',     progress >= 5,   '토픽 분석 중...',        '다음 미션 대기 중'],
                    ['researcher',  progress >= 20,  s.researcher,                '대기 중'],
                    ['writer',      progress >= 30,  s.writer,                    '대기 중'],
                    ['seo',         progress >= 55,  'SEO 타이틀 생성 중...',  '대기 중'],
                    ['persona',     progress >= 60,  '노르딕 후크 작성 중...','대기 중'],
                    ['visual',      progress >= 65,  '이미지 프롬프트 설계 중...', '대기 중'],
                    ['pmid',        progress >= 70,  'PubMed PMID 검증 중...', '대기 중'],
                    ['automation',  progress >= 75,  'HTML 조립 중...',        '대기 중'],
                    ['critic',      progress >= 85,  s.critic,                    '대기 중'],
                    ['analyst',     progress === 0,  '일일 성과 분석 중...',  '대기 중'],
                    ['ceo',         true,            s.ceo,                       '시스템 점검 중'],
                ];

                agentMap.forEach(([cls, active, activeMsg, idleMsg]) => {
                    const balloon = document.querySelector(`.agent.${cls} .balloon`);
                    if (balloon) balloon.textContent = active ? activeMsg : idleMsg;
                });
            }

            // 현재 미션 및 진행률 연동
            if (REAL_DATA.currentMission) {
                const missionTitle = document.querySelector('.mission-title');
                const missionStep = document.querySelector('.mission-step');
                const progressBar = document.querySelector('.progress-bar');

                if (missionTitle) missionTitle.textContent = REAL_DATA.currentMission.title;
                if (missionStep) missionStep.textContent = `${REAL_DATA.currentMission.step} (${REAL_DATA.currentMission.progress}%)`;
                if (progressBar) progressBar.style.width = `${REAL_DATA.currentMission.progress}%`;
            }
        }
    }

    updateStats();

    // 3. 실시간 로그 반영
    const logStream = document.getElementById('log-stream');
    
    function updateLogs() {
        if (typeof REAL_DATA !== 'undefined' && REAL_DATA.logs) {
            logStream.innerHTML = ''; // 기존 로그 비우기
            REAL_DATA.logs.forEach(line => {
                const entry = document.createElement('div');
                entry.className = 'log-entry';
                if (line.includes('SUCCESS') || line.includes('발행 완료')) entry.classList.add('success');
                if (line.includes('🚨') || line.includes('ERROR') || line.includes('REJECTED')) entry.classList.add('warning');
                
                // 불필요한 타임스탬프 부분 간소화 (선택 사항)
                entry.textContent = line;
                logStream.appendChild(entry);
            });
        }
    }

    // 초기 로그 업데이트
    updateLogs();

    // 5초마다 데이터 파일 다시 로드 시도 (실제로는 페이지를 새로고침하거나 브라우저 캐시를 피해야 함)
    // 여기서는 간단히 30초마다 페이지 새로고침 제안 또는 수동 업데이트 안내
    setInterval(() => {
        // 로컬 파일의 경우 script 태그를 다시 로드하는 방식으로 업데이트 가능
        const oldScript = document.querySelector('script[src="data.js"]');
        if (oldScript) {
            const newScript = document.createElement('script');
            newScript.src = 'data.js?v=' + Date.now();
            oldScript.parentNode.replaceChild(newScript, oldScript);
            setTimeout(() => {
                updateLogs();
                updateStats();
            }, 500);
        }
    }, 3000); // 3초마다 갱신

    // 3. 에이전트 랜덤 움직임
    const agents = document.querySelectorAll('.agent');
    agents.forEach(agent => {
        setInterval(() => {
            if (Math.random() > 0.8) {
                const currentTop = parseFloat(agent.style.top);
                const currentLeft = parseFloat(agent.style.left);
                
                const newTop = currentTop + (Math.random() - 0.5) * 5;
                const newLeft = currentLeft + (Math.random() - 0.5) * 5;
                
                // 범위 제한
                if (newTop > 30 && newTop < 70) agent.style.top = newTop + '%';
                if (newLeft > 20 && newLeft < 80) agent.style.left = newLeft + '%';
            }
        }, 3000);
    });

    console.log("NutriStack Dashboard v5.4.3 Initialized.");
});
