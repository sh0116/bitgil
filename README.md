# 빛길 (Bitgil)

> 시각장애인을 위한 LLM 실시간 화면 해설 — **한국어 학습(인강·도표·수식)을 우선**으로,
> 스크린리더의 사각지대를 메우는 오픈소스 도구
>
> An open-source tool that uses vision LLMs to narrate the screen in real time for
> blind and low-vision users — leading with Korean-language learning (lectures,
> charts, equations), delivered as an NVDA add-on and a platform-agnostic web client.

[![License: GPLv2 (addon)](https://img.shields.io/badge/addon-GPLv2-blue.svg)](LICENSE)
[![License: MIT (core)](https://img.shields.io/badge/core-MIT-green.svg)](core/LICENSE)
[![License: CC BY 4.0 (profiles)](https://img.shields.io/badge/profiles-CC%20BY%204.0-orange.svg)](profiles/LICENSE)

---

## 한 줄 요약 / One-liner

스크린리더(NVDA)가 읽지 못하는 화면 — 그래프와 도표가 가득한 강의 자료, 수식, 접근성이
구현되지 않은 프로그램 — 을 비전 LLM이 실시간으로 추론하여, 시각장애인 곁에서 함께 화면을
봐주는 친구처럼 음성으로 해설해주는 오픈소스 도구.

## 어디에 집중하나 / Focus (근거 기반)

1차 웨지는 **한국어 학습**(인강·도표·수식)이다. 이유는 근거에 있다:

- **언어 moat:** NVDA 애드온 스토어 503개 중 한국어(`ko`) 번역이 **0개**. 한국어 학습
  맥락은 비어 있다.
- **충족되지 않은 실수요:** 시각장애인 230명 중 학업 도표를 AI로 읽는 비율은 **7.5%**,
  **50%는 여전히 사람에게 물어본다**. "누가 대신 봐줘야 하는" 문제가 남아 있다.
- **게임은 후속:** VLM 전용 게임 해설은 성공률을 못 높인다는 연구(GamerAstra)로 근거가
  반박된다. 게임 프로파일은 유지하되 flagship에서 내렸다.

또한 국내 유통이 센스리더 보조금 채널 중심이라 **무료 애드온이 배제**되는 구조여서,
플랫폼 무관 **웹 클라이언트 + MIT 코어**를 애드온만큼(또는 그 이상) 중요한 자산으로 본다.
자세한 근거·출처는 [docs/evidence.md](docs/evidence.md).

## 왜 만드는가 / Why

스크린리더는 개발자가 미리 심어둔 텍스트(대체 텍스트, ARIA 레이블)만 읽을 수 있다. 게임 화면,
강의 슬라이드의 도표, 수학 그래프처럼 **시시각각 변하는 시각 중심 화면**은 스크린리더의
사각지대다. 우리는 화면을 만드는 쪽이 접근성을 심어주길 기다리는 대신, **화면을 보는 쪽에
지능을 부여한다.**

## 핵심 기능 / Core Features

| ID | 기능 | 설명 |
|----|------|------|
| F1 | 라이브 해설 모드 (Live Narrator) | 화면 변화를 감지해 "무엇이 어떻게 바뀌었는지" 증분 해설 |
| F2 | 대화형 질의응답 (Ask the Screen) | 현재 화면에 대해 언제든 질문 |
| F3 | 도메인/커뮤니티 프로파일 팩 | YAML로 게임·학습 플랫폼별 해설 설정을 커뮤니티가 기여 |
| F4 | 학습 특화 기능 | 그래프·차트 심층 설명, 수식 낭독, 복습 노트 내보내기 |
| F5 | 멀티 프로바이더 + 로컬 LLM | OpenAI / Anthropic / Bedrock / Gemini / Ollama, BYO API Key |

## 프로젝트 구조 / Repository Layout

```
addon/        NVDA 애드온 본체 (GPLv2) — NVDA 프로세스 내에서 동작
core/         재사용 가능한 코어 로직 (MIT) — 프로바이더 어댑터, 변화 감지기 등
profiles/     기본 프로파일 팩 (CC BY 4.0)
docs/         한/영 문서
tests/        테스트
```

라이선스 이중 구조: NVDA가 GPLv2이므로 애드온 본체는 GPLv2, 다른 스크린리더/독립 앱으로의
이식성을 위해 코어 로직은 MIT로 분리. 자세한 근거는 [docs/licensing.md](docs/licensing.md).

## 단축키 / Keyboard Shortcuts

| 단축키 | 기능 |
|--------|------|
| `NVDA+Shift+E` | 라이브 해설 켜기/끄기 (F1) |
| `NVDA+Shift+A` | 현재 화면에 질문 (F2) |
| `NVDA+Shift+N` | 세션 복습 노트를 마크다운으로 내보내기 (F4) |

프로바이더·API 키·해설 밀도는 NVDA 설정의 **Bitgil (빛길)** 패널에서 조정합니다.

## 프로토타입 바로 실행 / Try it now (no NVDA)

애드온과 동일한 코어 파이프라인을 CLI로 실행합니다:

```bash
pip install -e ./core[dev]
python scripts/bitgil_demo.py --image slide.png --provider anthropic --profile learning-chart
```

`.nvda-addon` 빌드: `python scripts/build_addon.py` → `dist/bitgil-<version>.nvda-addon`.
자세한 사용법은 [docs/development.md](docs/development.md).

## 개발 상태 / Status

🚧 **M1~M3 코드 완료 (프로토타입 동작).** 라이브 해설·질의응답·복습 노트·설정 패널·프로파일
팩 6종·CLI 프로토타입·애드온 빌드까지 동작합니다. 남은 것은 실기기(데스크톱 NVDA + 실 API
키/로컬 모델) 피드백 기반 튜닝. 로드맵은 [docs/roadmap.md](docs/roadmap.md)를 참고하세요.

## 시작하기 / Getting Started

```bash
# 코어 패키지 개발 설치
pip install -e ./core[dev]

# 테스트
pytest
```

NVDA 애드온 빌드 및 설치 방법은 [docs/development.md](docs/development.md) 참고.

## 기여 / Contributing

코드 기여(Python)와 비개발 기여(프로파일 팩 YAML, 용어집, 해설 품질 피드백)를 분리해
진입장벽을 최소화합니다. 시각장애인 당사자가 "이 게임의 해설이 이상하다"를 이슈로 올리는 것
자체가 1급 기여입니다. **"Nothing about us without us."**

[CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

## 라이선스 / License

- 애드온 본체 (`addon/`): **GPLv2**
- 코어 로직 (`core/`): **MIT**
- 프로파일 데이터 (`profiles/`): **CC BY 4.0**
