# NutriStack Lab — Agent OS Launch Guide 🚀

## 1. 개요
현재 워크스페이스는 `NutriStack Lab v4`의 강력한 자동화 로직과 `Agent OS`의 지능형 UI가 결합된 하이브리드 시스템입니다.

## 2. 핵심 컴포넌트
- **UI (TypeScript/VS Code)**: 에이전트와 대화하고, 작업 현황을 시각적으로 확인합니다.
- **Core (Python v4)**: 실제 블로그 포스팅 생성, 리서치, 배포를 담당하는 60여 개의 전문 스크립트.

## 3. 에이전트별 연결 도구 (Scripts)
에이전트에게 다음과 같이 명령하면 해당 스크립트를 실행합니다.

| 에이전트 | 실행 가능 스크립트 | 설명 |
|:--|:--|:--|
| **Dr. 리서처** | `pubmed_fetcher.py`, `Researcher_Manager.py` | 최신 논문 리서치 및 성분 분석 |
| **트렌드 헌터** | `trend_hunter.py` | 실시간 구글 트렌드 및 키워드 발굴 |
| **콘텐츠 작가** | `Writer_Manager.py`, `retroactive_rewriter.py` | 블로그 초안 작성 및 기존 글 재집필 |
| **비주얼 셰프** | `Visual_Manager.py`, `image_restorer.py` | 이미지 생성 및 복구 |
| **블로거 마스터** | `Deployment_Manager.py`, `blog_sync.py` | Blogger 배포 및 동기화 |
| **팩트 체커** | `Critic_Manager.py` | 품질 검수 및 팩트 체크 |
| **CEO** | `00_NutriStack_Grand_Orchestrator_v5.py` | 전체 파이프라인 가동 |

## 4. 바로 시작하기 (터미널)
모든 시스템을 한꺼번에 가동하려면 다음 명령어를 터미널에 입력하세요:
```bash
./start_nutristack.bat
```

또는 에이전트에게 **"전체 시스템 가동해줘"**라고 말하면 CEO 에이전트가 오케스트레이터를 실행합니다.
