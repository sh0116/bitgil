# 개발 로드맵 / Roadmap (약 4~5개월)

기획서 섹션 9 기준. 각 마일스톤은 검증 목표(Definition of Done)를 가진다.

## M1 — 파이프라인 검증  ✅ 코드 완료 (실기기 실측 대기)
- [x] NVDA 애드온 스캐폴딩 (AI-content-describer 소스 분석·참고)
- [x] 캡처 → LLM → 음성 출력 파이프라인 (`capture` → `NarrationEngine` → F2)
- [x] 프로바이더 어댑터 (`bitgil_core.providers`: Anthropic/OpenAI/Gemini/Ollama + 팩토리)
- **검증 목표:** Slay the Spire 화면 1장을 3초 내 해설 — *실 API 키 + 데스크톱 NVDA 필요*

## M2 — 라이브 모드 (F1)  ✅ 코드 완료 (실기기 실측 대기)
- [x] 변화 감지기 구현 (`bitgil_core.change_detect`: perceptual-hash + OCR diff 훅)
- [x] 세션 컨텍스트 = 증분 해설 (`bitgil_core.context`, `LiveNarrator`)
- [x] 끼어들기 정책 (`addon/.../output` SpeechBridge: queue/interrupt/defer)
- [x] 라이브 루프 (`bitgil_core.live.LiveNarrator`, F1 토글 배선)
- **검증 목표:** 카드 게임 한 판을 라이브 해설만으로 진행 — *실기기 필요*

## M3 — 프로파일 & 학습 모드 (F2, F3, F4)  🚧 진행 중
- [x] YAML 프로파일 시스템 (`bitgil_core.profiles`) + 관찰 주기(`observe_interval`)
- [x] 질의응답 F2 (Ask the Screen) — `NVDA+shift+a`
- [x] 복습 노트(markdown) 내보내기 F4 (`bitgil_core.review`) — `NVDA+shift+n`
- [x] NVDA 설정 패널 (프로바이더 / API 키 / 모델 / 해설 밀도)
- [x] OCR 어댑터(`bitgil_core.ocr`, rapidocr) → 변화 감지기 연결
- [x] 프로파일 팩 선택 UI (설정 패널에서 6종 YAML 팩 로드/선택)
- [x] CLI 프로토타입(`scripts/bitgil_demo.py`) + 애드온 빌드(`scripts/build_addon.py`)
- [ ] 그래프 심층 설명 실사용 튜닝 (프로파일 프롬프트는 존재) — 실기기 피드백 후

## M4 — 사용자 검증 & 커뮤니티
- 시각장애인 사용자 테스트 (게임 3명 + 인강 3명 이상 목표)
  - 협력 타진: 한국시각장애인연합회, 넓은마을 등
- `bitgil-profiles` 저장소 공개 (초기 프로파일 6종)
- 피드백 반영

## M5 — 제출 준비
- 한/영 문서화
- NVDA Add-on Store 등록 절차 착수
- 기능 테스트 리포트 / 라이선스 검정 리포트
- 데모 영상 (게임 한 판 + 인강 그래프 이해 시나리오)

## M6 — 앰비언트 데스크톱 코파일럿 (탐색/설계)  📐 설계 확정
한 앱의 비전 내레이터에서, 화면 전체를 함께 보며 사용자의 모든 활동을 공유하는
앰비언트 코파일럿으로. 특정 앱에 종속되지 않고, 갑작스러운 팝업·알림을 **맥락 있게
해석하고 지능적으로 끼어드는** 방향. 전체 설계는 [ambient-copilot.md](ambient-copilot.md).
- 계층형 아키텍처: 구조화 OS 이벤트(UIA/토스트/프로세스) → 선택적 비전-LLM 해석
  (실시간성은 구조화 데이터에서 나온다 — Minecraft 접근성 사례 교훈)
- [x] 인터럽트 트리아지 코어 프로토타입 (`bitgil_core.triage`): 이벤트 → LLM 분류 →
  결정론적 안전 정책 → `interrupt/queue/suppress`. 오프라인 테스트 완료(`tests/test_triage.py`).
- [x] 플랫폼 무관 웹 레퍼런스 클라이언트 (`web/`): getDisplayMedia 화면 스트리밍 →
  기존 코어(`NarrationEngine`/`ChangeDetector`) 재사용 → Web Speech 낭독. NVDA·OS 불필요.
  엔드포인트: `/narrate`, `/narrate/stream`(F1 문장 스트리밍), `/triage`(트리아지 배선).
- [x] AWS Bedrock 프로바이더 (`bitgil_core.providers.bedrock_provider`): AWS 자격증명
  체인으로 Claude 호출. 실기기 검증 완료(ap-northeast-2, Claude 3.5 Sonnet, 스캠·권한 팝업 분류).
- [x] 목표 추적기(`bitgil_core.goal.GoalTracker`) — 최근 활동 컨텍스트를 트리아지
  관련성 판단에 공급(웹 백엔드 배선).
- [x] 결정론적 안전 휴리스틱(`bitgil_core.safety`) — 스캠/보안 프롬프트 키워드로
  LLM 분류를 **상향만**(never downgrade) 보정. 파싱 실패 시에도 스캠 탐지.
- [x] 웹 클라이언트 마감 — `/configure`(프로파일·밀도 실시간 반영), 프로파일 드롭다운,
  오류 UX.
- [x] NVDA 스텁 하니스(`tests/test_addon.py`) — 가짜 NVDA 모듈로 `SpeechBridge` 정책·
  inference glue를 오프라인 테스트 + `windows-latest` CI 잡(pytest + 애드온 빌드/아티팩트).
- [x] 애드온 순수 파이썬 의존성 벤더링(PyYAML) — NVDA 내부에서 프로파일 로드 가능.
- 남은 것(실기기 필요): OS 이벤트 소스(UIA/토스트) 연결 + `SpeechBridge` 실배선;
  네이티브 의존성(Pillow/imagehash)·프로바이더 SDK 플랫폼 휠 번들.
- 목표/맥락 추적, 안전 분류기(가짜 백신·스캠 팝업 구분, 보안 프롬프트 자동클릭 금지),
  대화형 질의 + 확인 기반 대리 조작
- 대상: 특히 어린 시각장애 아동의 Windows·검색·앱 사용 진입장벽 완화 + 교육 모드

## 리스크 & 대응 (섹션 7)
- **지연:** 1차 타깃을 턴제·학습으로, 스트리밍 문장 낭독, 소형 비전 모델 우선.
  실시간 게임은 명시적으로 후속 과제(`game-realtime` 프로파일 주석 참고) — LLM 왕복이
  물리적 하한. 구현된 지연 레버: ① 프로파일 `speed` 티어(fast→Haiku/Flash 등 빠른 모델
  자동 선택, `bitgil_core.providers.base.model_for_speed`), ② 프레임 다운스케일
  (`bitgil_core.image_ops.downscale_png` + 프로파일 `max_image_dim` — 업로드/비전 토큰 절감),
  ③ 변화 감지 게이팅, ④ 문장 단위 스트리밍.
- **환각:** "보이는 것만/불확실하면 불확실하다" 프롬프트 강제, 중요 수치는 OCR 대조
- **비용:** 변화 감지 게이팅 + 로컬 모델, 1시간 사용 비용 문서화
- **EULA:** 게임 파일 미수정, 화면 캡처만 (FA11y 노선)
