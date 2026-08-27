# 작업 규칙 / Working rules for this repo

빛길(Bitgil) — 시각장애인을 위한 비전 LLM 실시간 화면 해설. 배경·근거는 [README.md](README.md),
지금 무엇이 막혀 있고 다음에 무엇을 할지는 **[docs/handoff.md](docs/handoff.md)를 먼저 읽으세요**.

## 이 프로젝트에서 지켜야 할 것

- **낭독 대상이 사용자다.** 프로바이더가 올린 예외 문구는 웹/애드온에서 **음성으로 읽힙니다**
  (`web/server.py`가 `{"text": "오류: <exception>"}`로 답함). 그래서 오류 메시지는
  "조치할 수 있는 한국어 한 문장"이어야 합니다. 상태코드만 던지지 마세요.
- **환각은 안전 문제입니다.** BLV 사용자는 AI 오류를 약 50%만 잡아냅니다
  ([docs/evidence.md](docs/evidence.md)). 화면에 없는 수치를 지어내지 않게 하는 프로파일 규칙,
  이미지를 못 보는 모델에 이미지를 넘기지 않는 라우팅은 **기능이 아니라 안전장치**입니다.
- **애드온 의존성 제약:** 애드온에는 PyYAML만 벤더링됩니다. NVDA 프로세스에서 실행되는 경로는
  벤더 SDK를 import하면 안 됩니다(그래서 `omniroute_provider`는 `requests`만 쓰고,
  `endpoint_errors.py`가 `base.py`와 분리돼 있습니다).
- **라이선스 이중 구조:** `addon/` GPLv2, `core/` MIT, `profiles/` CC BY 4.0. 코어에
  스크린리더·OS 의존 코드를 넣지 마세요.

## 흐름

1. `main`에 직접 커밋하지 않습니다. 브랜치 → PR → **오너가 직접 머지**합니다(자동 머지 금지).
2. 머지 전 통과해야 하는 것: `python -m pytest -q`, `ruff check core/ tests/ scripts/`, 시크릿 스캔.
3. 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` 트레일러를 붙입니다.

```bash
source .venv/bin/activate
python -m pytest -q                        # 오프라인 테스트 (현재 293개)
ruff check core/ tests/ scripts/
```

## 하지 말 것

- **실 API 키를 커밋하지 않습니다.** `.env`는 gitignore. 템플릿은 `.env.example`. BYO API Key.
- **모델 ID를 "고치지" 마세요.** `claude-opus-4-8`, `claude-sonnet-5`,
  `claude-haiku-4-5-20251001`는 **유효한** ID입니다.
- **Ollama를 다시 권하지 마세요.** 오너 환경에서 동작하지 않는다고 확인됐고, 실 LLM 경로는
  **OmniRoute만** 지원합니다.
- `safety.apply_policy`는 없습니다. 함수는 `triage.apply_policy`(들어오는 이벤트 분류)이고,
  나가는 동작의 게이트는 `agent/automator.py::gate_action`입니다.

## 환경

- 개발기는 **라즈베리파이(ARM64 Linux)** — NVDA(Windows 전용)가 여기서 돌지 않습니다. QA는
  플랫폼 무관 코어 + `web/` 클라이언트 + 키 없는 `demo` 프로바이더로 합니다([docs/qa.md](docs/qa.md)).
- 오너의 실사용 테스트 기기는 **맥**입니다. 실 LLM은 로컬 OmniRoute 게이트웨이(포트 20128).
