# NutriStack Lab — 전체 시스템 맵 (2026-06-03)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                        NUTRISTACK LAB PIPELINE v9.4                         ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│  ① SCHEDULER  (daily_scheduler_v5.py)                                       │
│                                                                              │
│   06:00 ──► Google Trends (7d×4 + 30d×3 + 3m×2 + 1yr×1 가중합산)           │
│              └─► 127개 후보 중 점수 상위 1~2개 가이드 선택                  │
│              └─► 롱테일 1개 선택 (synergy/antagonism/timing)                │
│   07:00~22:30 ► 사람처럼 불규칙한 시간에 RAW 파일 생성 → 00_Raw/          │
│                  (v8.7: 균등분배+jitter, count=N 항상 N개 보장)              │
│                                                                              │
│   [topic_bank.json] ◄──── longtail_pipeline.py                              │
│   343개 토픽                                                                 │
│   ├─ comprehensive_guide  127개  (영양소 기본 가이드)                        │
│   ├─ friend_experience    144개  (지인 시점 2:8 전략)                        │
│   ├─ symptom_query         20개  "Always Tired After Lunch..."               │
│   ├─ question_query         20개  "Why Isn't My Zinc Working..."             │
│   ├─ combination_query     134개  "Can You Take Zinc and Copper Together"    │
│   │    └─ 발행 영양소끼리만 조합 / 새 글 발행 시 자동 갱신                  │
│   ├─ timing/synergy/antagonism  32개  (롱테일)                               │
│   └─ [2:8 비율] plan_today → published_links 체크 → friend 우선 배정        │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ RAW 파일 (topic + type + sections)
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ② ORCHESTRATOR  (00_NutriStack_Grand_Orchestrator_v5.py)                   │
│                                                                              │
│  [v8.9 루프 버그 수정] scheduled_time 대기 파일만 있을 때 sleep(30) 추가    │
│  (기존: sleep 없이 초당 3~4회 루프 → 로그 폭발. 수정 후: 30초 간격)        │
│                                                                              │
│  [v9.4 Critic 판정 구조] blocking 체크 → Critic AI 앞으로 이동              │
│  ├─ blocking 이슈 있으면: Critic AI 스킵, 즉시 반려 (1.5분 낭비 제거)       │
│  ├─ score < 70%: Critic AI 스킵, 즉시 반려                                  │
│  └─ 조건 통과 시에만: Critic AI 실행 (피드백 전용)                           │
│                                                                              │
│  [v9.4 auto_sanitize_html] body 본문 "complete/ultimate guide" 전역 제거    │
│  (H1만 교체하던 기존 → body text까지 확장 → AI_Footprint 사전 차단)         │
│                                                                              │
│  ┌──────────┐    ┌──────────────────┐    ┌──────────┐    ┌──────────┐     │
│  │RESEARCHER│───►│  WRITER          │───►│ TEACHER  │───►│  EDITOR  │     │
│  │(gemma4)  │    │  + 페르소나 분기 │    │ (Critic) │    │  (PPV)   │     │
│  └──────────┘    └──────────────────┘    └──────────┘    └──────────┘     │
│                       │                                                     │
│               topic_type=friend_experience                                  │
│               → "지인이 주인공, Erik은 관찰자"                               │
│               → My Friend / A Colleague / A Guy at the Gym 화자             │
│       │               │               │                │                    │
│  PubMed API      7원칙 적용       루브릭 채점       7룰 검사                │
│  PMID 수집       경험담 ≥60%      9점 미달시        치환중복                │
│  논문 검증       비선형구조        재작성 루프       문장파손                │
│                  감정표현          LESSONS 추출      메타동기화              │
│                  실패담            → agent_lessons   경험담비율              │
│                  모호한결론        → dynamic_rules   과장탐지                │
│                  단정표현금지★     → shared_brain    독자시점(AI)            │
│                  ('seemed to'      ────────────────────────────             │
│                   'for me at       [v8.9 각인] BANNED_PHRASES:              │
│                    least' 등)      단정표현 5개 자동치환 추가               │
│                                                                              │
│  _sync_all_meta() ────► H1 = OG = JSON-LD = JS (6곳 통일, 발행 전)         │
│                                                                              │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ 검증 통과 HTML
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ③ PUBLISHER  (Blogger API)                                                  │
│                                                                              │
│   publish_to_blogger() ──► Blogger CDN                                      │
│   │                         └─► nutristacklab.com                           │
│   └─► published_links.json 기록 (topic_type 포함)                           │
│   └─► topic_bank completed 마킹                                              │
│   └─► 가이드 진행 현황: 20/131 ██░░░░░░░░                                  │
│   └─► Diversity Score 계산 (diversity_checker.py)                           │
│        제목패턴(최근10) + 구조(최근20) + 변화포인트(최근20) → 0~100         │
│        WARN 전용 — FAIL 없음 / Telegram 알림에 포함                         │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ post_id + diversity_score
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ④ PPV — Post Publish Verifier  (post_publish_verifier.py)                  │
│                                                                              │
│   [채점]                    [Editor 7룰]            [PPV Loop]              │
│   A: 제목/SEO               Rule1 치환중복           9.0 미달시              │
│   B: 메타/이미지             Rule2 문장파손           최대 5회               │
│   C: 콘텐츠 품질             Rule3 제목동기화         외과적 수정            │
│   D: 기술/링크               Rule4 설명동기화         섹션별 추출            │
│   E: YMYL/브랜드             Rule5 경험담비율★          Claude 재작성          │
│   F: 구조                    Rule6 과장탐지★            → Blogger 패치        │
│   (★ = v8.9 강화)           Rule7 독자시점(AI)                               │
│                                                                               │
│   [v8.9] Rule5 타입별 경험담 비율 (_RATIO_MAP):                              │
│   comprehensive_guide  45~55%  │  how_i_use/personal_guide  60~75%           │
│   experiment_log       60~70%  │  wrong_culprit             65~80%           │
│   unexpected_tradeoff  65~80%  │  regret_ignoring           65~80%           │
│   기타(longtail 등)    60~75%  │  미달/초과 모두 WARN                        │
│                                                                               │
│   [v8.9] 경험담 = 내경험(I/my/me) + 주변인경험(친구/파트너/지인/포럼)       │
│   내경험 : 주변인 권장 2:8 — 주변인 < 내경험×0.5 이면 WARN                 │
│   social_markers 우선 분류 (my friend > my 충돌 방지)                        │
│                                                                               │
│   [v8.9] 단정 표현 감지 → 즉시 REJECT:                                      │
│   'makes you stronger', 'X does nothing', 'basically useless',               │
│   'absorption depends on', 'is essential' → 완화 표현 재작성 요구            │
│   og:description: 연구/정보형 금지 → 개인 경험형 필수                        │
│                                                                               │
│   [v9.2] F2: display:none 픽셀 스킵 → 실제 hero 이미지 탐색                  │
│   [v9.2] A1: YMYL 제목 — Healed/Cured/Eliminated → BAD_TITLE_WORDS 차단     │
│   [v9.2] B1: og:description 오염 강화 (the research on / studies show)       │
│   [v9.2] var desc 없으면 <h1> 앞 자동 주입                                   │
│   [v9.2] bulk_verify: Claude Haiku AI 연결 (B1 자동 재작성)                  │
│                                                                              │
│   S≥9.0 ──► good_examples + Teacher T3 성공각인                            │
│   정체 2회 ► Teacher T1 근본분석 → core_lessons                            │
│   5회 소진 ► Teacher T2 AVOID → dynamic_rules                              │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⑤ 학습 뇌  (20_Meta/)                                                      │
│                                                                              │
│  agent_lessons.json    ◄── Critic LESSONS 블록 파싱                         │
│  (Writer/Critic 교육)       고빈도 → core_lessons 자동 승격                 │
│                        ◄── [v8.9] 단정표현 금지 Tier1 (count=5)             │
│                             경험담비율 60%+ Tier1 (count=5)                 │
│                                                                              │
│  core_lessons.json     ◄── count≥3 자동 승격                                │
│  (장기 핵심 기억)       ◄── [v8.9] 단정표현·비율 Tier1 핵심 각인            │
│                                                                              │
│  dynamic_rules.json    ◄── PPV AVOID 패턴  (총 92개 규칙)                   │
│  (금지 패턴 DB)             Editor 7룰 규칙                                  │
│                        ◄── [v8.9] WRITER/CRITIC 단정·비율 4개 추가          │
│                                                                              │
│  shared_brain.json     ◄── DO/AVOID 패턴 집계                               │
│  (Writer 공유 두뇌)         good_examples 성공각인                           │
│                             Post-Processing Editor 역할                      │
│                                                                              │
│  good_examples.json    ◄── S등급 달성 포스팅                                │
│  (성공 사례 DB)             Teacher T3 각인                                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ⑥ 지원 시스템                                                               │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ hernex_agent.py │  │  bot_start.py   │  │morning_report.py│             │
│  │ Telegram 봇     │  │  Discord 봇     │  │ 07:00 일일리포트│             │
│  │ /ceo /approve   │  │  상태 모니터링  │  │ 학습엔진 실행   │             │
│  │ /lesson /audit  │  │                 │  │                 │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────────────────────────────┐                                │
│  │  telegram_poster.py                     │                                │
│  │  발행 알림: 제목/점수/가이드진행현황     │                                │
│  │  📋 [██░░░░░░░░] 20/131 완료            │                                │
│  └─────────────────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ⑦ 학습 루프 (자동 진화)                                                     │
│                                                                              │
│  글 생성 → Critic 탈락 → LESSONS 추출 → agent_lessons 저장                 │
│      ▲                                         │                            │
│      │          count≥3 → core_lessons         │                            │
│      │          Blogger 각인 → Writer 참조 ◄───┘                            │
│      │                                                                       │
│  PPV S등급 달성 → good_examples → shared_brain DO 패턴                     │
│  PPV 정체 → dynamic_rules AVOID → 다음 글부터 자동 회피                    │
│                                                                              │
│  결과: 경험담↑ 실패담↑ 과장↓ 제목-본문일치↑ (실제 개선 확인됨)            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ⑨ SITE BRAIN  (site_brain.py)  — v9.0  ★신규                               │
│                                                                              │
│  "이 글이 좋은가?" → "이 사이트가 좋은가?" 레이어                            │
│                                                                              │
│  [카테고리 택소노미]                                                          │
│  minerals 25% │ vitamins 20% │ performance 18% │ sleep_stress 12%           │
│  gut_metabolism 10% │ longevity 8% │ cognitive_mood 7%                      │
│                                                                              │
│  [3가지 분석]                                                                 │
│  category_balance()    현재 vs 목표 비율 → 과잉(BLOCK) / 부족(BOOST)        │
│  cluster_completeness() 영양소별 5슬롯 완성도 (guide/timing/dosage/mistake) │
│  topic_authority()     영양소별 편수 (3편+ = adequate)                       │
│                                                                              │
│  [허브 페이지]  hub_page_generator.py                                        │
│  7개 카테고리 허브 Blogger 발행 완료                                          │
│  새 글 발행 시 → 해당 허브 자동 링크 추가 (orchestrator 훅)                  │
│                                                                              │
│  [plan_today() 연동]                                                          │
│  트렌드 60% + Site Brain 40% 가중 합산                                       │
│  BLOCK -40pt │ BOOST +20pt │ 매일 06:00 자동 실행                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ⑧ DIVERSITY SCORE  (diversity_checker.py)  — v8.5                          │
│                                                                              │
│  품질 점수와 완전 독립. FAIL 없음. WARN + 피드백 루프.                       │
│                                                                              │
│  비교 3축 (가중합산):                                                        │
│  ┌──────────────────────┬────────────────────────────────┬─────────────┐   │
│  │  제목 패턴 × 30%     │  스토리 구조 × 40%             │ 변화포인트  │   │
│  │  최근 10개 대비       │  최근 20개 대비                 │   × 30%    │   │
│  └──────────────────────┴────────────────────────────────┴─────────────┘   │
│                                                                              │
│  8개 스토리 구조:                                                            │
│  ① skeptic_to_convert   회의→전환           (기존)                          │
│  ② mistake_to_fix       실수→수정           (기존)                          │
│  ③ struggle_to_solution 고투→해결           (기존)                          │
│  ④ delayed_realization  뒤늦은 깨달음       메라토닌/어댑토젠               │
│  ⑤ wrong_culprit        엉뚱한 범인         미네랄 상호작용                 │
│  ⑥ experiment_log       실험 일지           생강/프로바이오틱스             │
│  ⑦ unexpected_tradeoff  예상 못한 부작용    마그네슘/고용량                 │
│  ⑧ regret_ignoring      무시했다 후회       커뮤니티 스타일                 │
│                                                                              │
│  목표 비율 (STRUCTURE_TARGETS):                                              │
│  skeptic 20% / mistake 15% / struggle 15% / delayed 15%                     │
│  wrong_culprit 15% / experiment 8% / tradeoff 7% / regret 5%                │
│                                                                              │
│  피드백 루프 (실시간 비율 비교, 자동 언블락):                                │
│  현재 비율 >= 목표×1.5 → AVOID 자동 → Writer 프롬프트 주입                  │
│  현재 비율 <  목표×0.5 → RECOMMEND 자동                                     │
│  비율 회복 시 → 자동 언블락. 별도 리셋 없음.                                │
│                                                                              │
│   70+ ✅ high   50~70 🔵 ok   ~50 ⚠️  warn → 다음 글 구조 교체              │
└─────────────────────────────────────────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════════╗
║  현재 상태 (2026-06-03)  v9.8                                                ║
║  LIVE: 28개 전원 S등급  │  평균 9.5+/10  │  가이드 20/131  │  토픽뱅크 477개 ║
║  허브 페이지: 7개 │ 26편 등록(중복제거) │ 자동업데이트 정상  │  Site Brain: 활성 ║
║                                                                              ║
║  v8.7: 스케줄러 균등분배+jitter / 발행시간 07:00~22:30 확장                 ║
║  v8.8: PPV→Writer 핫주입 / LessonLifecycle Decay / 타입별 ratio             ║
║  v8.9: 루프sleep버그수정 / 단정표현금지 Tier1각인 / 경험담비율 세분화       ║
║  v9.0: SiteBrain / 허브7개 / friend_experience 2:8 / symptom+question쿼리   ║
║  v9.1: combination_query 134개 / 새 글 발행 시 자동 갱신                    ║
║  v9.2: PPV F2픽셀버그 / A1YMYL / B1강화 / var desc자동주입 / bulk AI연결    ║
║  v9.3: hermes_queue 377→0 정리 / VRAM 클리어 / GPU 점유 해결                ║
║  v9.4: Critic blocking체크선행(1.5분낭비제거) / body complete guide제거      ║
║  v9.5: 재시작processing고착자동복원 / ask_ai keep_alive 1분설정              ║
║  v9.6: RAW파싱type#제거 / NoPlaceholder비blocking / Pre-QC meta주입 / _p2_score버그 ║
║  v9.7: 허브자동업데이트수정(stdout→logging) / 기존24개소급등록           ║
║  v9.8: 허브중복제거(50→26) / 각인학습완료(dynamic_rules114개) / VitD수술  ║
╚══════════════════════════════════════════════════════════════════════════════╝
```
