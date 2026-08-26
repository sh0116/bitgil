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

| ID | 기능 | 설명 | 상태 |
|----|------|------|------|
| F1 | 라이브 해설 모드 (Live Narrator) | 화면 변화를 감지해 "무엇이 어떻게 바뀌었는지" 증분 해설 (문장 단위 스트리밍) | ✅ 코드 |
| F2 | 대화형 질의응답 (Ask the Screen) | 현재 화면에 대해 언제든 질문 | ✅ 코드 |
| F3 | 도메인/커뮤니티 프로파일 팩 | YAML로 게임·학습 플랫폼별 해설 설정을 커뮤니티가 기여 (기본 6종) | ✅ 코드 |
| F4 | 학습 특화 기능 | 그래프·차트 심층 설명, 수식 낭독, 복습 노트 내보내기(기계생성 고지·출처 포함) | ✅ 코드 |
| F5 | 멀티 프로바이더 + 로컬 LLM | Anthropic / Bedrock / OpenAI / Gemini / Ollama, BYO API Key | ✅ 코드 |

### 앰비언트 데스크톱 코파일럿 (M6) — 코어 구현 완료

한 앱의 내레이터를 넘어, 화면 전체에서 갑자기 뜬 팝업·알림을 **맥락 있게 해석하고 지능적으로
끼어드는** 계층. 전체 설계는 [docs/ambient-copilot.md](docs/ambient-copilot.md).

| 컴포넌트 | 역할 | 상태 |
|----------|------|------|
| 인터럽트 트리아지 (`bitgil_core.triage`) | 데스크톱 이벤트 → LLM 분류 → **결정론적 안전 정책** → `interrupt/queue/suppress` + `needs_confirmation` | ✅ 오프라인 테스트 |
| 안전 휴리스틱 (`bitgil_core.safety`) | 스캠·보안 프롬프트 키워드로 LLM 판단을 **상향만**(never downgrade) 보정. 파싱 실패에도 방어 | ✅ 오프라인 테스트 |
| 목표 추적기 (`bitgil_core.goal`) | 최근 활동 맥락을 트리아지 관련성 판단에 공급 | ✅ |
| 플랫폼 무관 웹 클라이언트 (`web/`) | getDisplayMedia 화면 스트리밍 → 코어 재사용 → Web Speech 낭독. NVDA·OS 불필요 | ✅ |

> **안전 원칙:** 권한·보안 프롬프트와 스캠 의심 창은 항상 표면화하고 `needs_confirmation`을
> 세워 **대리 클릭을 원천 차단**한다. BLV 사용자는 AI 오류를 약 50%만 잡아낸다는 근거
> ([evidence.md](docs/evidence.md))에 따라, 자율 대행이 아니라 **안내 우선**을 택한다(M7).

## 프로젝트 구조 / Repository Layout

```
addon/        NVDA 애드온 본체 (GPLv2) — NVDA 프로세스 내에서 동작
core/         재사용 가능한 코어 로직 (MIT) — 스크린리더·OS 무관, 오프라인 테스트 가능
  bitgil_core/
    capture, change_detect/, image_ops   캡처 · 변화 감지(perceptual-hash+OCR) · 다운스케일
    engine, context/, live, postprocess/  해설 엔진 · 세션 컨텍스트 · 라이브 루프 · 문장 후처리
    profiles, ocr, review                 YAML 프로파일 · OCR 어댑터 · 복습 노트(F4)
    triage, safety, goal                  앰비언트 코파일럿: 트리아지 · 안전 · 목표 추적
    providers/                            anthropic·bedrock·openai·gemini·ollama·omniroute + 팩토리
web/          플랫폼 무관 웹 레퍼런스 클라이언트 (키 없는 demo 프로바이더 내장)
scripts/      CLI 프로토타입(bitgil_demo) · 애드온 빌드(build_addon)
profiles/     기본 프로파일 팩 6종 (CC BY 4.0)
docs/         한/영 문서 (설계·근거·QA·로드맵)
tests/        오프라인 테스트 156개 (코어·애드온 스텁·트리아지·웹 서버·프로바이더 등)
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

**① 키 없이(무료) 웹 클라이언트로 — 이 Pi에서도 바로 됩니다.**
`demo` 프로바이더가 캡처→변화감지→해설→음성 파이프라인 전체를 API 키 없이 돌립니다:

```bash
pip install -e ./core[dev]
python web/server.py            # http://localhost:8765 (기본 demo 프로바이더)
```

실 모델로 바꾸려면 `--provider anthropic --profile learning-chart` 등을 지정합니다.
화면 공유(getDisplayMedia)는 secure context 전용이라 **localhost로 열거나** 원격이면
`ssh -L 8765:localhost:8765 <pi>`로 터널링하세요.

**② 실 LLM을 벤더 키 없이 — 로컬 OmniRoute 게이트웨이.**
[OmniRoute](https://github.com/diegosouzapw/OmniRoute)(MIT)는 여러 상위 프로바이더를
OpenAI 호환 엔드포인트 하나로 묶어주는 자체 호스팅 게이트웨이입니다. 기본이 키 없음이고
HTTP만 쓰므로 `omniroute` 프로바이더는 **추가 SDK가 필요 없습니다**(코어 의존성 `requests`만).

```bash
python web/server.py --provider omniroute --profile learning-chart
python scripts/bitgil_demo.py --image slide.png --provider omniroute
# 게이트웨이가 다른 포트/호스트면: --base-url http://localhost:20128/v1
```

모델은 OmniRoute의 콤보 채널로 지정합니다(`auto/best-vision` 기본, 프로파일 speed 티어가
`quality`면 `auto/pro-vision`). **주의:** `auto/vision`·`auto/multimodal`은 후보 풀의 컨텍스트
한도가 작아 스크린샷을 거부하므로 기본값으로 쓰지 않습니다. 무료 풀은 상위 제공자의
쿼터·IP 제한에 걸릴 수 있고, 그때는 게이트웨이 오류 메시지가 그대로 전달됩니다.

**③ 이미지 한 장을 CLI로 — 실 프로바이더/로컬 모델 필요.**

```bash
python scripts/bitgil_demo.py --image slide.png --provider anthropic --profile learning-chart
# 로컬 모델: --provider ollama --model llava
```

**④ `.nvda-addon` 빌드:** `python scripts/build_addon.py` → `dist/bitgil-<version>.nvda-addon`.
자세한 사용법은 [docs/development.md](docs/development.md). QA 재현·시나리오는 [docs/qa.md](docs/qa.md).

## 개발 상태 / Status

🚧 **M1~M3 코드 완료 + M6(앰비언트 코파일럿) 코어 구현 완료 — 프로토타입 동작.**

- **동작:** 라이브 해설(문장 스트리밍)·질의응답·복습 노트·NVDA 설정 패널·프로파일 팩 6종·
  CLI·애드온 빌드, 그리고 인터럽트 트리아지·안전 휴리스틱·목표 추적·플랫폼 무관 웹 클라이언트.
- **검증:** 오프라인 테스트 **116개 통과**, ruff clean, 시크릿 스캔 clean. 최근 QA 라운드에서
  가드레일·파이프라인·프로바이더·웹 결함을 코드 점검으로 찾아 회귀 테스트와 함께 수정
  ([docs/qa.md](docs/qa.md)). AWS Bedrock은 실 자격증명으로 검증(ap-northeast-2).
- **남은 것(실기기 필요):** 데스크톱 NVDA에서의 음성/끼어들기 실배선, OS 이벤트 소스(UIA/토스트)
  연결, 실 LLM 해설 **품질** 튜닝(오류·환각률). 아래 "남은 태스크" 참고.

로드맵 전체는 [docs/roadmap.md](docs/roadmap.md), 우선순위 백로그는 [docs/backlog.md](docs/backlog.md).

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
