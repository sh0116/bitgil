# 아키텍처 / Architecture

기획서 섹션 6 기준.

```
┌────────────────────────────────────────────────────┐
│ NVDA 애드온 (addon/, GPLv2)                            │
│                                                      │
│  캡처 파이프라인 (capture/)                             │
│   ├─ 화면/창 캡처 (mss)                                │
│   ├─ 변화 감지기 → bitgil_core.change_detect          │
│   │   → "의미 있는 변화"일 때만 다음 단계로               │
│   └─ 관심 영역(ROI) 크롭 (프로파일 힌트 기반)             │
│                                                      │
│  추론 레이어 (inference/)                              │
│   ├─ 프로바이더 어댑터 → bitgil_core.providers         │
│   ├─ 세션 컨텍스트 → bitgil_core.context              │
│   └─ 응답 후처리 → bitgil_core.postprocess            │
│                                                      │
│  출력 레이어 (output/)                                 │
│   ├─ NVDA speech API (스크린리더 음성으로 직접 출력)      │
│   ├─ 끼어들기 정책 (SpeechBridge)                       │
│   └─ 세션 로그 → 복습 노트(markdown)                    │
│                                                      │
│  프로파일 시스템 (profiles/)                            │
│   └─ bitgil_core.profiles + bitgil-profiles 동기화   │
└────────────────────────────────────────────────────┘
```

## 설계 원칙
1. **NVDA를 대체하지 않고 보강** — 접근성이 구현된 부분은 NVDA가, 사각지대는 애드온이.
2. **LLM 호출은 이벤트 기반** — 변화 감지 시에만 호출해 비용·지연 절제.
3. **애드온 자체가 100% 키보드·음성으로 조작 가능**해야 함.

## 계층 분리 (GPLv2 / MIT)
NVDA 종속 코드는 `addon/`에만 둔다. 재사용 가능한 순수 로직은 `core/`(MIT)에 두어
Orca 등 다른 스크린리더나 독립 앱으로 이식 가능하게 한다. 빌드 시 `bitgil_core`가
애드온 번들에 포함된다.
