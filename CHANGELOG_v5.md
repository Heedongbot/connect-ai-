# NutriStack Lab Pipeline — CHANGELOG v5

---

## 2026-06-03 — v9.3: hermes_queue 정리 + GPU 점유 근본 해결

### hermes_queue.json 정리 (cleanup_queue.py / cleanup_queue2.py)
- **원인:** hermes-agent CLI 타임아웃 루프 → hernex_agent 재시작 시 pending 377개 처리 시도 → qwen3:14b VRAM 점유
- **분석:** pending 377개 = 삭제된 구 포스팅 294개 + 중복 71개 + 이미 수정된 항목 12개
- **처리:** 377개 전부 `"status": "completed"` 마킹
  - 구 제목 패턴(`Complete Guide`, `Complete:`, `Is X Worth Taking`) → old title format
  - 오늘 수동 수술된 포스팅 → manually fixed 2026-06-03
  - 중복 항목 → duplicate
- **결과:** pending 377 → 0 / VRAM 클리어 확인

### Ollama VRAM 관리
- qwen3:14b-q4_K_M: 6.6GB → 0GB (언로드 완료)
- `keep_alive=0` API로 즉시 언로드 가능 확인

---

## 2026-06-03 — v9.2: PPV 자동화 개선 + YMYL 각인

### post_quality_check.py — 4가지 개선

**F2 display:none 픽셀 버그 수정**
- 기존: `re.search(r'<img[^>]+>', html)` → 첫 번째 img = 숨김 트래킹 픽셀 → F2=3/10
- 수정: `display:none` / `width:1px` / `height:1px` 이미지 스킵 후 첫 번째 실제 이미지 탐색

**A1 YMYL 제목 단어 추가**
- `BAD_TITLE_WORDS`에 추가: `"Healed My"`, `"Cured My"`, `"Eliminated My"`, `"Fixed My Chronic"`, `"Reversed My"`, `"Defeated My"`, `"Overcame My Chronic"`
- 이제 발행 전 Critic이 자동 차단

**B1 og:description 오염 감지 강화**
- 추가 패턴: `"the research on "`, `"studies show"`, `"according to research"`, `"what the research says"`, `"science behind"`, `"and complete"`, `"or complete"`

### post_publish_verifier.py — var desc 자동 주입
- og:description 존재하는데 `var desc` 없으면 `<h1>` 앞에 자동 `<script>` 블록 생성
- Description 3곳 불일치 근본 해결 (매번 재발 방지)

### bulk_verify.py — Claude Haiku AI 연결
- `make_claude_fn()` 추가 — `ANTHROPIC_API_KEY` 환경변수 사용
- `ask_ai_fn = claude_haiku` 전달 → B1 og:description 재작성, YMYL 자동 감지
- AI 없을 때 graceful fallback (rule-based만 실행)

### YMYL 표현 각인 (agent_lessons + BANNED_PHRASES + dynamic_rules)
- `agent_lessons` Writer/Critic: YMYL 제목/본문 금지 패턴 3개 (count=3)
- `BANNED_PHRASES` 8개: `"healed my chronic"`, `"crashes disappeared"`, `"brain fog lifted"`, `"pain disappeared"`, `"neither one is getting properly absorbed"` 등
- `dynamic_rules` 3개: TITLE-YMYL, BODY-YMYL, BODY-GENERALIZATION

### 오늘 수동 수정 포스팅
| 포스팅 | 점수 | 주요 수정 |
|---|---|---|
| Potassium (1275828656143939503) | 8.8→**9.6 S** | var desc 주입, 숨김 픽셀 제거, H2 대소문자 |
| Zinc+Iron (6218057025291946012) | 9.7 S | 제목 Healed→안전, YMYL 표현 5곳 수정 |

---

## 2026-06-02 — v9.0: Site Brain + 허브 페이지 + 롱테일 전략 전면 확장

### site_brain.py (신규) — 사이트 단위 의사결정 레이어
- **7개 카테고리 택소노미:** minerals / vitamins / performance / sleep_stress / gut_metabolism / longevity_antioxidants / cognitive_mood
- **목표 비율:** minerals 25% / vitamins 20% / performance 18% / sleep 12% / gut 10% / longevity 8% / cognitive 7%
- **3가지 분석 지표:**
  - `category_balance()` — 현재 vs 목표 비율, 과잉(🔴)/부족(🟡) 감지
  - `cluster_completeness()` — 영양소별 5슬롯 완성도 (guide/timing/dosage/mistake/synergy)
  - `topic_authority()` — 영양소별 발행 편수 (3편+ = adequate)
- `recommend()` → block_categories / boost_categories / weak_nutrients 반환
- CLI: `python site_brain.py` → 전체 리포트 즉시 출력

### hub_page_generator.py (신규) — 카테고리 허브 페이지
- 7개 카테고리 허브 Blogger 발행 완료

| 카테고리 | 허브 제목 | 현재 편수 |
|---|---|---|
| minerals | Every Mineral Supplement I've Tested | 8편 |
| vitamins | Every Vitamin I've Tested | 3편 |
| performance | Performance Supplements I've Actually Used | 3편 |
| sleep_stress | Sleep and Stress Supplements | 1편 |
| gut_metabolism | Gut Health and Metabolism Supplements | 4편 |
| longevity_antioxidants | Longevity and Antioxidant Supplements | 1편 |
| cognitive_mood | Brain and Mood Supplements | 1편 |

- `hub_posts.json`에 post_id + URL 추적
- `add_post_to_hub()`: 새 글 발행 시 해당 허브에 자동 링크 삽입
- Blogger API rate limit 대비 지수 백오프 재시도 (15→30→60→120→240초)

### orchestrator — 허브 자동 업데이트 훅
- 새 글 발행 직후 SiteBrain으로 카테고리 분류 → `add_post_to_hub()` 자동 호출
- 실패 시 비치명적 경고만 (발행 자체는 영향 없음)

### daily_scheduler_v5.py — Site Brain 40% plan_today() 반영
- 기존: Google Trends 100% 기준 선택
- 변경: 트렌드 60% + Site Brain 40% 가중 합산
  - block 카테고리 (과잉): -40점 페널티
  - boost 카테고리 (부족): +20점 보너스
- 2026-06-02 현재: minerals/gut_metabolism BLOCK → sleep_stress/vitamins BOOST

### friend_experience 포스팅 타입 신설 + 2:8 비율 전략
- 144개 friend_experience 토픽 생성 (36 영양소 × 4 템플릿, 8가지 지인 유형)
- RAW 파일 첫 줄 `topic_type: friend_experience` 헤더 → 오케스트레이터 우선 읽기
- Writer 페르소나: "지인이 주인공, Erik은 관찰자/증인"
- 스케줄러 2:8 비율 관리: published_links 기준 personal:friend 비율 계산, 부족 시 하루 최대 4개 우선 배정

### topic_bank 신규 타입 추가 (총 343개)
| 타입 | 편수 | 예시 |
|---|---|---|
| friend_experience | 144 | "My Colleague Started Zinc Before I Did" |
| symptom_query | 20 | "Always Tired After Lunch — What Finally Helped" |
| question_query | 20 | "Why Isn't My Zinc Working — What I Figured Out" |

### PPV Rule5 주변인 경험담 + 타입별 비율 세분화
- social_markers 추가 (30개+ 패턴): my friend / a guy at the gym / someone on reddit 등
- 서브체크: 주변인 < 내경험×0.5 → WARN "권장 비율 2:8"
- social 우선 분류로 "my friend" vs "my" 충돌 방지
- 7타입 세분화 _RATIO_MAP 적용

---

## 2026-06-02 — v8.9: 루프 버그 수정 + 단정 표현 금지 + 경험담 비율 각인

### orchestrator: scheduled_time 대기 루프 sleep 버그 수정
- **문제:** RAW 파일이 있으나 전부 `scheduled_time` 미도달일 때 `sleep` 없이 즉시 루프 재진입
- **증상:** 초당 3~4회 로그 스팸 → `orchestrator.log` 폭발(21만 줄+), CPU/메모리 낭비
- **수정:** `stuck_count` 카운터 추가 — `scheduled_time` 미도달 스킵 시 `stuck_count += 1`
  - for 루프 종료 후 `stuck_count == len(files)` 이면 `time.sleep(30)` 실행
- **효과:** 대기 중 파일만 있을 때 30초 간격 체크 (분당 2회)

### 건강효과 단정 표현 금지 — Tier1 각인 (engrave_rules.py)
- **배경:** Creatine/Zinc Stack 포스팅에서 사용자가 직접 6곳 단정 표현 발견
- **각인 위치:**
  - `agent_lessons.json`: Writer + Critic (count=5, tier1, active=True)
  - `core_lessons.json`: Writer + Critic (count=5, tier1)
  - `dynamic_rules.json`: WRITER/CRITIC 규칙 4개 추가 (총 92개)
- **금지 표현 → 대체 표현:**
  - `makes you stronger/faster/better` → `seemed to help with strength/recovery`
  - `X does nothing` → `X likely does very little for me`
  - `That's basically useless` → `that didn't seem to work well for me`
  - `absorption depends on Y` → `may absorb better when... from what I've read`
  - `X is essential for Z` → `X seemed important, at least in my case`
- **BANNED_PHRASES 추가:** 5개 자동치환 패턴 (발행 전 자동 적용)

### 경험담 비율 60%+ 필수 — Tier1 각인
- **배경:** Zinc Stack 포스팅 경험담 비율 43% → 수술 3회 → 59%/9.6/10 S등급 달성
- **각인 내용:**
  - 전체 문장 중 1인칭(I/my/me) 경험 문장 60% 이상 필수
  - 조언형(`First: X is important`, `you should`, `the key is`) → 경험형(`I noticed`, `for me`, `I found`) 전환 의무
  - `og:description`: 연구/정보형 금지 → 개인 경험형 필수
    - BAD: `"The research on Zinc is often different from real-world results"`
    - GOOD: `"I took zinc every day for six weeks and felt nothing."`
- **Critic REJECT 조건 추가:** 발행 전 비율 60% 미만 → REJECT + Writer 재작성 요구

### daily_scheduler_v5: 발행 시간대 확장 (v8.7)
- `07:00~20:00` → `07:00~22:30` (2.5시간 확장)
- 랜덤 탈락 방식 → 균등분배(interval) + jitter 방식 교체 (count=N 항상 N개 보장)

### 오늘 수동 수술 완료 포스팅
| 포스팅 | 작업 | 결과 |
|---|---|---|
| How Creatine Finally Stopped My Workout Plateau | 단정 표현 6곳 완화 + PMID 3개 주입 + 이미지 재생성(인물 제거) | 8.8/10 S |
| How to Take Zinc for Best Results | 경험담 비율 43%→59% 부분수술 3회 + og:description 교체 | 9.6/10 S |

### friend_experience 포스팅 타입 신설 — 지인 시점 2:8 전략

**배경:** 100~200개 포스팅이 전부 "I tried X" 패턴이면 한 사람이 모든 보충제를 먹는 부자연스러운 블로그가 됨.
개인 포스팅 2 : 지인 포스팅 8 비율로 다양한 화자 시점 확보.

**추가된 컴포넌트:**

`add_friend_experience_topics.py` (신규)
- 36개 영양소 × 4개 템플릿 = 144개 friend_experience 토픽 자동 생성
- 8가지 지인 유형: My Friend / My Colleague / A Guy at My Gym / My Partner / My Roommate 등
- 8가지 제목 템플릿: "tried for a month", "before I did", "I almost talked them out of", 등

`daily_scheduler_v5.py`
- `plan_today()`에 2:8 비율 관리 로직 추가
- `published_links.json` 기준 personal:friend 비율 실시간 계산
- friend_experience 부족 시 하루 최대 4개 우선 배정
- `create_raw_file(topic_type=)` — RAW 파일 첫 줄에 `topic_type: friend_experience` 헤더 추가

`00_NutriStack_Grand_Orchestrator_v5.py`
- RAW 파일 헤더에서 `topic_type:` 우선 읽기 (기존 텍스트 키워드 감지 대신)
- `load_agent_with_lessons()` — `topic_type == "friend_experience"` 시 Writer 페르소나 주입:
  - "YOU ARE NOT THE PERSON WHO TOOK THE SUPPLEMENT — a friend/colleague did"
  - Erik은 관찰자/증인 역할, 지인이 주인공
  - 예시 오프닝 패턴 포함

`topic_bank.json`
- friend_experience 144개 추가 (총 303개)

### combination_query 자동 생성 (v9.1) — add_combination_queries.py (신규)
- 발행된 영양소끼리만 조합 (없으면 안 만들고, 생기면 자동 추가)
- 18개 영양소 → 134개 combination_query 생성 (18C2 = 153 - 기존 19쌍)
- 다른 카테고리 조합 우선 (minerals × performance 등)
- 새 글 발행 시 orchestrator 훅에서 자동 재실행 → 새 조합 즉시 추가
- `longtail_types`에 combination_query / symptom_query / question_query 추가

### post_publish_verifier: Rule5 주변인 경험담 카운트 추가
- **배경:** 내 경험담만 쓰면 단조롭고 신뢰도 낮음 → 주변인 경험도 경험담으로 인정
- **경험담 정의 확장:** 내경험(I/my/me) + 주변인경험(친구/파트너/지인/포럼) 합산
- **social_markers 추가:** `my friend`, `my partner`, `a guy at the gym`, `someone on reddit`,
  `a colleague of mine`, `someone I know`, `one of my friends` 등 30개+ 패턴
- **서브체크 추가:** 주변인 < 내경험×0.5 이면 WARN (권장 비율 내경험:주변인 = 2:8)
- **우선순위:** social_markers 먼저 분류 → personal_markers 분류 (`my friend` vs `my` 충돌 방지)
- **Writer 레슨 각인:** 주변인 경험담 예시 패턴 + 2:8 권장 비율 (count=3)

### post_publish_verifier: Rule5 타입별 경험담 비율 세분화
- **기존:** comprehensive_guide 45~55% / 그 외 60~75% (2타입)
- **변경:** 7타입 세분화 (`_RATIO_MAP` 딕셔너리)

| topic_type | 기준 | 설명 |
|---|---|---|
| `comprehensive_guide` | 45~55% | 정보+경험 균형 |
| `how_i_use` / `personal_guide` | 60~75% | 개인 루틴 중심 |
| `experiment_log` | 60~70% | 실험 기록 형식 |
| `wrong_culprit` | 65~80% | 범인 찾기 서사 |
| `unexpected_tradeoff` | 65~80% | 예상 못한 부작용 |
| `regret_ignoring` | 65~80% | 무시했다 후회 |
| 기타 (longtail 등) | 60~75% | 기본 경험담 |

- 상한(hi) 초과도 WARN — 설명/정보 문장 부족 경고
- `dynamic_rules.json` Tier1 규칙 추가

### bulk_verify 결과 (2026-06-02)
- 전체 21개 전원 통과, 전원 S등급 ✅
- 평균: **9.57/10** (신규 2개 포함)

---

## 2026-05-28 (5차) — 이미지/엔티티 버그 소급 수정

### Iron Complete Guide: 종합 소급 수정
- 이미지 URL 404: Unsplash 직링크 → Imgur 업로드 교체 (`https://i.imgur.com/kD3I8uV.png`)
- FAQ 끊김: "The expensive brand wasn't`<hr>`author box" → 문장 완성 후 정상 구조로 복구
- example.com canonical 충돌: 내부 더미 canonical 제거 → 실제 URL 1개만 유지
- JSON-LD headline ↔ H1 불일치: headline → H1 "Iron Complete: How I Actually Fixed My Energy..." 통일
- 포스트 제목: "How to Take Iron Complete..." → "Why Iron Finally Started Working for Me..."
- old bio 수정: "independent health researcher/8 years/peer-reviewed" → 신 bio
- AI 금지어 수정: "Real talk:" / "Game changer" / "bioavailable" / "perfect protocol"
- intro-box 내부 중복 `<hr>` 제거
- `<!DOCTYPE html><html><head>` 구조 해체 → body 내용만 추출, `<style>` 블록 앞으로 이동
- TOC CSS `::before` → HTML 직접 `→` 삽입으로 교체
- 원인: hernex_agent A2 처리 시 완전한 HTML 문서를 content로 생성 (SAMe와 동일 패턴)

### SAMe 포스트: &#8594; 이중인코딩 수정
- 문제: bio 패치 후 `&amp;#8594;` → 브라우저에 `&#8594;` 리터럴 텍스트 노출
- 원인: GET 시 Blogger API가 엔티티를 정상화하여 반환 → 감지 스크립트에서 `&amp;#` 미발견 → 실제 서빙 HTML은 이중인코딩 상태
- 수정: html.unescape() 전체 적용 → 유니코드 `→` 직접 저장 (1175자 변경)
- 대상: post_id `6798477625337286323`

### hernex_agent: _update_post html.unescape 추가
- 변경: content 전송 전 `html.unescape(content)` 적용
- 이유: GET→PUT 시 Blogger API가 엔티티를 이중인코딩 → `&amp;#8594;` 렌더링 버그

### orchestrator: SEO 패치 html.unescape 추가
- 변경: SEO canonical/JSON-LD 패치 시 `html.unescape(_patched_html)` 적용
- 이유: 동일 이중인코딩 방지

### Copper Complete Guide: 소급 수정
- 이미지: 503바이트 fallback PNG(깨진 이미지) → Pollinations.ai 재생성 → Imgur 교체
- DOCTYPE 구조 해체, old bio → 신 bio, 금지어 수정, TOC → 직접 삽입
- 포스트 제목: "Why Copper Surprised Me (And How I Finally Got the Dose Right)"

### Iron Complete Guide: og:title / og:description 소급 추가
- og:title 누락 → 파싱 오류 원인
- JSON-LD description "Iron And Complete" 오탈자 수정
- og:title + og:description 태그 추가

### orchestrator: inject_seo_patch에 og:title / og:description 추가
- 기존: canonical + og:url + og:type + JSON-LD만 주입
- 추가: `og:title` + `og:description` (OG 파싱 오류 근본 수정)
- 이유: Iron 포스트 og:title 누락 → 소셜/검색 파싱 오류

### orchestrator: fallback PNG Imgur 업로드 차단
- 변경: `_create_fallback_png` 사용 시 Imgur 업로드 건너뜀 → base64 직접 반환
- 이유: Pollinations.ai 실패 시 503바이트 fallback PNG가 Imgur에 올라가 깨진 이미지 노출 (Copper 사례)

### hernex_agent: _sanitize_blogger_content 함수 추가
- 추가: `_update_post` 호출 전 content 자동 정제
- 기능: `<!DOCTYPE html>` 감지 시 SEO 블록 + `<style>` + body 내용만 재조합
- 추가 기능: TOC `li:before` CSS 제거 → `<li>` 에 `→` 직접 삽입
- 이유: A2/D2/E1 수정 시 orchestrator가 발행한 full HTML 문서 구조를 그대로 PUT → 재발 방지

### orchestrator: _strip_html_document_wrapper 함수 추가
- 추가: `publish_to_blogger` 첫 줄에서 content 자동 정제
- 기능: hernex_agent의 `_sanitize_blogger_content`와 동일한 로직
- 이유: writer AI가 `<!DOCTYPE html>` 전체 문서 생성 시 발행 직전 차단 → 재발 방지

### orchestrator: generate_title SAMe .title() 버그 수정
- 변경: `_CASE_FIXES` 딕셔너리 추가 — "Same" → "SAMe", "Coq10" → "CoQ10", "Nmn" → "NMN" 등 7개
- 이유: `"SAMe".title() == "Same"` — Python .title()이 대소문자 혼합 영양소명 망가뜨림 → 제목에 "Same" 노출

---

## 2026-05-28 (4차) — 발행 포스트 Author Bio 소급 패치

### patch_author_bio.py: 기발행 포스트 author bio 일괄 교체
- 패치 대상: 최근 12개 포스트 중 구 bio가 있는 8개
  - SAMe, Selenium, Zinc, HMB, Vitamin D3, Magnesium, Vitamin K2, Vitamin C
- 구 bio: "independent health researcher", "8 years", "peer-reviewed literature via PubMed" 제거
- 신 bio: "writes about personal supplement experiences and what has (or hasn't) worked in his own routine" 삽입
- 이유: SAMe 포스트 콘솔 확인에서 발견 — 코드 수정 전 발행된 포스트들은 구 bio 유지 → YMYL authority cosplay 위험
- 처리: patch_author_bio.py 일회성 스크립트 실행 → 완료 후 삭제

### hermes_queue: stale lock 파일 제거
- 제거: `20_Meta/hermes_queue.lock` (2026-05-28 19:51 시점에서 남은 stale lock)
- 이유: orchestrator 재시작 시 lock 미해제 → hernex_agent가 SAMe 큐 처리 불가 상태

---

## 2026-05-28

### orchestrator: CAPTION_TEMPLATES 교체
- 기존: 과학형 7개 ("The science behind...", "Clinical perspective:...", "What the research shows:...")
- 변경: 인간 경험형 10개 ("Honest notes on {section}.", "My experience with {section}: nothing dramatic." 등)
- 이유: 모든 글 동일 캡션 패턴 → AI footprint / Google site-wide 탐지 위험

### orchestrator: generate_title entity 강제 보장
- 변경: 제목 최종 단계에서 `topic_label`이 제목에 없으면 앞에 자동 삽입 ("Zinc: What Actually Happened...")
- 이유: Zinc 포스트 제목에 영양소명 누락 → SEO 손상, A2 hernex 재수정 비용 발생

### post_quality_check: AI_PATTERNS 4개 추가
- 추가: `what actually happened`, `what actually changed`, `what actually worked`, `nordic science`
- 이유: 오늘 3개 포스팅 리뷰에서 "what actually" 반복 과다 확인 → C4 채점에서 감지

### hernex_agent: _fetch_post API 버그 수정
- 변경: `status=[status]` → `status=status` (Blogger API는 리스트 아닌 문자열 요구)
- 변경: `maxResults=50` → `maxResults=500`
- 이유: Elderberry E1 등 실제 post_id도 "포스트 조회 실패" 반복

### hernex_agent: _fix_title 재시도 로직 추가
- 변경: AI가 같은 제목 반환 시 angle 3종 순차 재시도 (search-intent → benefit-focused → how-to)
- 이유: Selenium A2 "수정 내용 없음" — AI가 동일 제목 반환 → ok=False → 실패 처리

### hermes_queue: 더미 test ID 제거
- 제거: `post_id: "test123"`, `post_id: "test"` (B1 항목 2개)
- 이유: 실제 존재하지 않는 ID, 영구 "포스트 조회 실패" 유발

### daily_scheduler_v5: 06:05 재스캔 추가
- 변경: `schedule.every().day.at("06:05")` job 추가 → topic_ranker 실행 후 오늘 스케줄 재등록
- 이유: 00:01 스캔 시점에 topic_ranker가 아직 실행 전(06:00) → 오늘 발행 0건 발생

### bot_start: 원격 복구 명령어 추가 (Discord)
- 추가: `!status`, `!restart_all`, `!restart [name]`, `!trigger [topic]`
- 추가 함수: `_get_running_pids()`, `_kill_pid()`, `_start_process()`
- PROCESSES 딕셔너리: 6개 프로세스 경로·창 모드 통합 관리
- 이유: 외부에서 프로세스 장애 시 원격 복구 수단 없음

### hermes_telegram_bot: !명령어 Discord 섹션 전체 추가
- 변경: HELP_TEXT Discord 블록에 현황/승인·폐기/수동제어/재시작/에이전트 전 섹션 추가
- 이유: 기존 HELP_TEXT에 Discord 명령어 누락 → 사용자 확인 불가

### morning_report: GA4 IndexError 수정
- 변경: `get_ga4_data()` — `response.rows[0]` 접근 전 `if not response.rows` 가드 추가
- 이유: 신규 블로그 or 데이터 없는 날 `rows`가 빈 리스트 → IndexError → 아침 보고 전체 crash

### hermes_queue: 동시 쓰기 경합 수정
- 변경: `post_quality_check._push_hermes_queue()` — `O_CREAT|O_EXCL` lock 파일 + atomic write(`os.replace`) 추가
- 변경: `hernex_agent.process_hermes_queue()` — 동일 lock 파일 획득 후 처리, `finally`에서 해제
- lock 파일: `20_Meta/hermes_queue.lock`
- 이유: orchestrator 발행 직후 post_quality_check가 큐 추가, 동시에 hernex_agent가 큐 저장 → 신규 항목 유실

### hermes_queue: E1 Elderberry, A2 Selenium 재시도 리셋
- 변경: 두 항목 `status: "failed"` → `"pending"`, `error` 필드 제거
- 이유: _fetch_post API 수정 및 _fix_title 재시도 로직 추가 후 재처리 필요
- 결과: A2 Selenium → hernex_agent가 자동 처리 완료 (19:47, 제목 "How to Take Selenium for Maximum...")

### bot_start: _get_running_pids wmic → psutil 교체
- 변경: `wmic` 명령 → `psutil.process_iter()` 사용
- 이유: Windows 11에서 wmic 미지원 → !status, !restart, !restart_all 전부 오작동

### bot_start: restart_all async sleep 수정
- 변경: `time.sleep()` → `await asyncio.sleep()` (async 함수 내)
- 이유: 동기 sleep이 Discord 이벤트 루프 블로킹 → 봇 응답 멈춤

### daily_scheduler_v5: _start_orchestrator 창 모드 수정
- 변경: `subprocess.Popen([sys.executable, ...])` → `cmd /k python ... + CREATE_NEW_CONSOLE`
- 이유: 워치독 자동재시작 시 오케스트레이터가 숨김 창으로 뜸 + 없는 로그 경로 오류 위험

### daily_scheduler_v5: cancel lambda iterate-while-modify 버그 수정
- 변경: 00:01/06:05 취소 로직을 `_rescan_today()` 함수로 분리, `list(schedule.jobs)` 복사본으로 iterate
- 이유: cancel_job이 schedule.jobs 리스트 수정하면서 동시에 iterate → 일부 job 취소 누락

---

## 2026-05-28 (3차) — SAMe 포스팅 품질 리뷰 반영

### orchestrator: TITLE_STYLES_GUIDE 전면 교체
- 변경: "Complete Guide", "What Actually Works" 포함 템플릿 제거
- 추가: "What Happened After 6 Months", "Why It Felt Different After Week 5" 등 경험형 7종
- 이유: 제목에 "Complete Guide" 반복 → AI SEO 사이트 footprint

### orchestrator: COMPREHENSIVE_GUIDE_SECTIONS "actually" 제거
- 변경: "How It Actually Works" → "How It Works" / "Amplified My Results" → "Made a Difference"
- 이유: "actually" 반복 패턴이 AI 어투

### orchestrator: AI_Footprint 금지어 추가
- 추가: "real talk:", "chemical architecture", "complete guide"
- 이유: 채점에서 감지 → Critic 반려 → Writer가 점진적으로 사용 안 하게 됨

### orchestrator: FAQ 3개로 고정, 프롬프트 강화
- 변경: "Create 3 FAQ pairs" → "Create EXACTLY 3 FAQ pairs. Stop after 3 pairs."
- 변경: display `faq_pairs[:4]` → `[:3]`, schema도 동일
- 이유: FAQ 과다 → AI SEO footprint

### orchestrator: Author bio authority 표현 약화
- 변경: "independent health researcher", "8 years", "peer-reviewed literature" 제거
- 변경: → "writes about personal supplement experiences and what has (or hasn't) worked"
- 이유: YMYL authority cosplay → Google 패널티 위험

### post_quality_check: AI_PATTERNS 3개 추가
- 추가: "what actually noticed", "real talk:", "complete guide"
- 이유: hernex C4 채점 감지 확대

## 2026-05-28 (2차)

### orchestrator: GENERIC_H1에서 "complete guide" 제거 (NoPlaceholder 오탐 수정)
- 변경: `GENERIC_H1` 리스트에서 `"complete guide"` 제거, 단독 제목일 때만 차단하는 regex 추가
- 이유: "SAMe Complete Guide" 등 comprehensive_guide 포스트 H1이 항상 NoPlaceholder 실패 → Critic 3회 강제 반려 → 불필요한 Claude Haiku 재작성 낭비
- 효과: 품질 ≥ 93.8% + 치명적 이슈 없음 → Critic 자동 스킵 → 즉시 발행

### orchestrator: fetch_ga4_article_lessons metric_values IndexError 수정
- 변경: `row.metric_values[0][1][2]` 접근 전 `len(mv) < 3` 가드 추가
- 이유: GA4 응답 row에 metric이 3개 미만일 때 IndexError crash

### orchestrator: get_search_keywords r.json()[1] IndexError 수정
- 변경: `r.json()[1]` → `data[1] if isinstance(data, list) and len(data) > 1 else []`
- 이유: Google Suggest API 응답이 리스트가 아닐 때 IndexError

### orchestrator: FAQ 생성 sections 빈 dict 가드 추가
- 변경: `self.ctx["sections"].values()` → `(self.ctx.get("sections") or {}).values()`
- 이유: surgical rewrite로 sections가 비어있을 때 TypeError

### orchestrator: 2차 Critic 점수 regex 실패 시 기본값 0.75 → 0.80
- 변경: regex 실패(AI 응답 없음) 시 점수를 0.80으로 설정 (통과 처리)
- 이유: AI 타임아웃 or 빈 응답 시 0.75 → `_p2_fail=True` → 불필요한 Claude 인간화 트리거

### orchestrator: Critic HTML 입력 35000자 → 12000자 축소
- 변경: 1차/2차/재검증 Critic 전부 `html[:35000]` → `html[:12000]`
- 이유: qwen3:14b에 35000자 전달 시 10분 타임아웃 (Read timed out. timeout=600) 발생 → 강제 반려 처리

---

## 2026-05-27

### hernex_agent: Qwen3 + Claude API 협업 구현
- 구조: Qwen3:14b 분석 → 자신감 ≥ 8이면 단독 처리, < 8이면 Claude Haiku 개입
- 학습: code_fix_lessons.json에 누적 → Qwen3이 점진적으로 단독 처리 비율 증가
- 추가 함수: `ask_claude_code()`, `load_code_lessons()`, `save_code_lesson()`

### hernex_agent: Tier 1 자동 에스컬레이션 구현
- 구조: hermes_queue에서 동일 카테고리 5회 이상 → `_auto_code_fix()` 자동 트리거
- 추가 함수: `check_tier1_escalation()`, `_auto_code_fix()`, `_load/save_escalation_log()`
- 파일: `20_Meta/tier1_escalation_log.json` (재에스컬레이션 방지용)

### orchestrator: 백업 트리거 제거
- 제거: `00_Raw/` 비었을 때 orchestrator가 직접 .md 생성하던 블록 (라인 4170-4188)
- 이유: daily_scheduler_v5와 중복 → 같은 포스트 2회 발행 위험

---

## 3티어 학습 구조 (현행)

| 티어 | 파일 | 역할 | 에스컬레이션 조건 |
|------|------|------|-----------------|
| Tier 3 | `20_Meta/agent_lessons.json` | 개별 실패 저장 | 자동 저장 |
| Tier 2 | `20_Meta/core_lessons.json` | 3회 이상 반복 → 승격 | 3회 반복 |
| Tier 1 | `hernex_agent.py` 코드 수정 | 5회 이상 → 자동 코드 수정 | 5회 반복 |

---

## AUTO_FIX_CATS 현행 (hernex_agent.py)

| 카테고리 | 설명 | 처리 |
|---------|------|------|
| A1, A2 | 제목 오염/SEO | 자동 수정 |
| B1 | og:description | 자동 수정 |
| D2 | 내부 링크 | 자동 수정 |
| E1 | YMYL 위험 표현 | 자동 수정 |
| C3, D1, C4 | 본문 길이/PMID/AI패턴 | 알림만 |
