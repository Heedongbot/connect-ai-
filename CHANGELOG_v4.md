# NutriStack Lab Grand Orchestrator v4.0

## 🚀 v4.0 주요 변경사항

### 1. 이미지 처리 완전 개선
- Pollinations로 이미지 생성 → 로컬 저장 → Google Drive 업로드
- Drive 업로드 실패 시: 플레이스홀더 사용 (Pollinations URL 절대 포스팅에 삽입 안 함)
- 함수: `get_safe_image_url()`

### 2. FAQ 스키마 하드코딩 (AI 생성 금지)
- 코드로 직접 FAQPage 스키마 생성
- @type: "FAQPage" 100% 보장
- 함수: `build_faq_schema()`

### 3. PMID 검증 DB
- 카테고리별 검증된 PMID 목록 내장
- 중복 없이 랜덤 선택
- 딕셔너리: `PMID_DB`

### 4. Writer 섹션 분리 방지
- 각 섹션에 "ONE SECTION ONLY" 컨텍스트 주입
- 섹션별 Disclosure/H1/FAQ 생성 차단

### 5. HTML 조립 엔진
- `assemble_post()` 함수가 완전한 HTML 구조 보장
- H1 60자 강제 적용
- &#8594; 화살표 자동 사용
- 내부 링크 DB에서 랜덤 3개 선택

### 6. 품질 자동 검사
- `quality_check()` 10개 핵심 항목 자동 검증
- 점수 산출 후 Obsidian 학습 기록 저장

### 7. Obsidian 자기학습
- 포스팅 완료마다 성공/실패 기록
- `10_Wiki/Decisions/` 폴더에 마크다운 저장
- 다음 포스팅에서 RAG 참조 가능

---

## 📁 폴더 구조

```
NutriStack_Lab/
├── 00_Raw/              ← .txt 파일 넣으면 자동 처리
├── 01_Completed/        ← 완료된 파일 이동
├── 02_Checkpoints/      ← 중단 후 재시작용 체크포인트
├── 05_Images/           ← 생성된 이미지 로컬 저장
├── 05_style_guide/      ← 스타일 가이드
├── 06_prompts/          ← 에이전트 프롬프트
├── 10_Wiki/
│   └── Decisions/       ← Obsidian 학습 기록 (자동 저장)
└── 00_NutriStack_Grand_Orchestrator.py  ← 메인 실행 파일
```

---

## 🚀 실행 방법

```bash
# 1. 가상환경 활성화 (있는 경우)
# 2. 주제 파일 생성
echo "Magnesium L-Threonate" > 00_Raw/magnesium_threonate.txt

# 3. 오케스트레이터 실행
python 00_NutriStack_Grand_Orchestrator.py
```

---

## ⚠️ 주의사항

1. `client_secrets.json`과 `token.pickle` 필요 (Google API 인증)
2. Ollama 로컬 서버 실행 필요 (`ollama serve`)
3. gemma2:9b 및 gemma2:2b 모델 설치 필요
4. FAQ 스키마는 별도 Blogger HTML 위젯에 붙여넣기

---

## 📊 품질 체크 항목 (자동 검사)

| # | 항목 | 기준 |
|---|------|------|
| 1 | H1 길이 | 60자 이하 |
| 2 | H1 개수 | 정확히 1개 |
| 3 | Pollinations URL | 0개 |
| 4 | 빈 src | 0개 |
| 5 | 화살표 형식 | &#8594; 사용 |
| 6 | → 화살표 | 0개 |
| 7 | FAQPage 스키마 | 포함 |
| 8 | script 태그 | 포함 |
| 9 | Medical Disclaimer | 포함 |
| 10 | Disclosure | 포함 |
