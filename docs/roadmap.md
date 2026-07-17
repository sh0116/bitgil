# 개발 로드맵 / Roadmap (약 4~5개월)

기획서 섹션 9 기준. 각 마일스톤은 검증 목표(Definition of Done)를 가진다.

## M1 — 파이프라인 검증  ✅ 코드 완료 (실기기 실측 대기)
- [x] NVDA 애드온 스캐폴딩 (AI-content-describer 소스 분석·참고)
- [x] 캡처 → LLM → 음성 출력 파이프라인 (`capture` → `NarrationEngine` → F2)
- [x] 프로바이더 어댑터 (`bitgil_core.providers`: Anthropic/OpenAI/Ollama + 팩토리)
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

## 리스크 & 대응 (섹션 7)
- **지연:** 1차 타깃을 턴제·학습으로, 스트리밍 문장 낭독, 소형 비전 모델 우선
- **환각:** "보이는 것만/불확실하면 불확실하다" 프롬프트 강제, 중요 수치는 OCR 대조
- **비용:** 변화 감지 게이팅 + 로컬 모델, 1시간 사용 비용 문서화
- **EULA:** 게임 파일 미수정, 화면 캡처만 (FA11y 노선)
