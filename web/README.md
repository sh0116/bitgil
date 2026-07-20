# Bitgil 웹 클라이언트 (화면 스트리밍 레퍼런스)

> "화면은 그냥 화면이다" — OS/스크린리더 구분 없이, 브라우저 화면 공유만으로 실시간
> 해설을 받는 **플랫폼 무관 baseline** 클라이언트. NVDA 애드온은 이 그림에서 *구조화
> 데이터를 제공하는 옵션 어댑터*일 뿐입니다. 배경은 [../docs/ambient-copilot.md](../docs/ambient-copilot.md).

## 구조

```
브라우저 (얇은 어댑터)                     Python 백엔드 (기존 코어 재사용)
─────────────────────────                 ──────────────────────────────
getDisplayMedia 화면 캡처                  POST /narrate (JPEG bytes)
  → canvas 다운스케일(maxDim)      ──────▶   → ChangeDetector 게이트
  → /narrate 로 전송                          → NarrationEngine.narrate
  ← {changed, text, reason}       ◀──────   ← 해설 텍스트
  → Web Speech API (ko-KR) 낭독
```

코어(`bitgil_core`)는 **한 줄도 바뀌지 않습니다.** 웹은 그저 새로운 `FrameSource` +
`SpeechSink`입니다 — 피벗이 코드로 증명되는 지점.

## 실행

```bash
# 자격증명 없이 바로 (데모 프로바이더 — 파이프라인 전체가 동작)
python web/server.py
#  → http://localhost:8765 를 브라우저에서 열고 "화면 공유 시작"

# 실제 해설 (예: Anthropic, ANTHROPIC_API_KEY 환경변수 필요)
python web/server.py --provider anthropic --profile learning-chart

# AWS Bedrock (Claude) — API 키 대신 AWS 자격증명 체인(~/.aws) 사용
BITGIL_AWS_REGION=ap-northeast-2 python web/server.py --provider bedrock
```

프로바이더: `demo`(기본) · `anthropic` · `bedrock` · `openai` · `gemini` · `ollama`.
프로파일 팩은 `../profiles/*.yaml` 6종을 그대로 사용합니다.

## 엔드포인트

| 메서드 · 경로 | 입력 | 반환 | 용도 |
|---|---|---|---|
| `POST /narrate` | JPEG/PNG bytes | `{changed, text, reason}` | 프레임 1회 해설 |
| `POST /narrate/stream` | JPEG/PNG bytes | 줄 단위 문장 스트림 | F1 문장 스트리밍(체감 지연↓) |
| `POST /triage` | DesktopEvent JSON | `{action, spoken, ...}` | 이벤트 트리아지(앰비언트 코파일럿) |
| `GET /config` | — | 프로바이더/프로파일 | 클라이언트 초기화 |

**트리아지 예시** (브라우저는 OS 이벤트를 못 만들므로 curl/OS 어댑터로 구동):

```bash
# 가짜 백신 팝업 → 스캠 탐지 → interrupt + 경고
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"kind":"dialog","text":"바이러스 감지! 무료 백신 설치","stole_focus":true}' \
  http://localhost:8765/triage
# → {"action":"interrupt","spoken":"주의: 사기(스캠)로 의심되는 창입니다. …","reason":"suspected-scam"}
```
안전 규칙(스캠 경고·보안 프롬프트 자동클릭 금지·분류 실패 시 큐잉)은 `bitgil_core.triage`의
결정론적 `apply_policy`에 있어 데모 프로바이더로도 폴백 동작합니다(실제 분류는 real provider 필요).

## ⚠️ Secure context (중요)

`getDisplayMedia`는 **secure context에서만** 동작합니다 — 즉 페이지가 **localhost**이거나
**HTTPS**여야 합니다. `http://<ip>:8765` 처럼 다른 기기에서 평문 HTTP로 열면 화면 공유가
조용히 차단됩니다.

- **가장 쉬움**: 백엔드와 브라우저를 같은 기기(localhost)에서.
- **이 Pi를 백엔드로, 노트북 브라우저에서** 쓰려면 SSH 터널로 localhost처럼 보이게:
  ```bash
  ssh -L 8765:localhost:8765 <pi-호스트>
  # 노트북 브라우저에서 http://localhost:8765
  ```
- 또는 리버스 프록시/`mkcert`로 HTTPS를 붙입니다.

## 지연·비용 레버 (이미 반영)

- **클라이언트 다운스케일**: 프레임 최장변을 `maxDim`(프로파일 `max_image_dim`, 기본 1280px)으로
  줄여 업로드·비전 토큰 절감.
- **변화 감지 게이팅**: 백엔드 `ChangeDetector`가 "의미 있는 변화"일 때만 LLM 호출.
- **관찰 주기 / 해설 밀도 / speed 티어**: 프로파일과 UI 컨트롤로 조절.

## 알려진 한계 (프로토타입)

- 단일 사용자(전역 엔진 1개). 다중 세션은 세션별 엔진 분리가 필요.
- "읽기"만 보편적입니다. 대리 조작(클릭/입력)은 플랫폼별 입력 주입이라 여기 없음.
- 트리아지는 별도 `/triage` 엔드포인트로 제공됩니다. 연속 화면 해설(`/narrate`)과
  이벤트 트리아지는 성격이 달라(전자는 스트림, 후자는 이산 이벤트) 의도적으로 분리했습니다.
  실제 OS 이벤트 소스(UIA/토스트) 연결은 후속(실기기).
