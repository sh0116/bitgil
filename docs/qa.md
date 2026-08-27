# QA 시나리오 & 테스트 자료 / QA Scenarios & Test Plan

> 이 문서는 빛길의 **주요 시나리오**를 정의하고, 각각을 **Pi에서 오프라인으로 재현**하는
> 방법·기대 결과·합격 기준을 적는다. 1차 웨지가 한국어 학습이므로([evidence.md](evidence.md))
> 학습 시나리오(강의·차트·수식·복습 노트)를 앞에 두고, 안전 시나리오(트리아지)를 뒤에 둔다.
>
> **테스트 환경 제약:** 개발기가 Raspberry Pi(ARM64 Linux)라 NVDA(Windows 전용)는 여기서
> 돌지 않는다. 그래서 QA는 **플랫폼 무관 코어 + 웹 클라이언트 + 키 없는 `demo` 프로바이더**로
> 수행한다(자세한 근거는 [architecture.md](architecture.md), [ambient-copilot.md](ambient-copilot.md)).
> 실제 LLM 품질(해설 정확도)은 실 프로바이더/실기기 단계에서 별도로 튜닝한다([user-testing.md](user-testing.md)).

## 0. 어떻게 재현하나 (오프라인 스모크)

키 없이 전체 파이프라인(캡처→변화감지→해설→음성)을 돌리는 `demo` 프로바이더가 있다.

```bash
# 코어 설치 + 자동화 스모크(웹 엔드포인트 + 코어 파이프라인)
pip install -e ./core[dev]
pytest tests/test_web_server.py -v

# 수동 확인: 데모 프로바이더로 웹 백엔드 기동 후 curl
python web/server.py --port 8766 --profile learning-chart
curl -s http://127.0.0.1:8766/config
curl -s -X POST --data-binary @slideA.png http://127.0.0.1:8766/narrate
```

전체 회귀:

```bash
source .venv/bin/activate && python -m pytest -q      # 전 테스트
ruff check core/ tests/ scripts/                       # 린트
```

### 0-1. 벤더 키 없이 **실 LLM**로 — 로컬 OmniRoute 게이트웨이

`demo`는 캔에 담긴 문장이라 해설 *품질*은 검증할 수 없다. 실 비전 모델을 벤더 API 키 없이
붙이려면 로컬 [OmniRoute](https://github.com/diegosouzapw/OmniRoute) 게이트웨이(기본 포트
20128, OpenAI 호환)를 띄우고 `omniroute` 프로바이더를 쓴다. 추가 SDK는 필요 없다.

```bash
curl -s http://localhost:20128/v1/models | head -c 200      # 게이트웨이 생존 확인
python scripts/bitgil_demo.py --image chart.png --provider omniroute
python web/server.py --provider omniroute --profile learning-chart
```

**측정된 제약 (라즈베리파이 + OmniRoute v16, 2026-08-26):**

| 콤보 채널 | 스크린샷 요청 결과 |
|-----------|--------------------|
| `auto/vision`, `auto/multimodal` | **400** — 후보 전원이 컨텍스트 한도 미달("~1225 tokens") → 기본값으로 부적합 |
| `auto/best-free` | **400** — 비전 지원 확정 타깃 없음 |
| `auto/best-vision`, `auto/pro-vision` | 비전 모델로 라우팅됨(현 상태 429 rate limit) → **기본값 채택** |
| `aug/*` (Augment) | 502 — 구독 인증 필요 |

**콤보는 보장이 아니다 (같은 날, 맥 + OpenRouter만 연결된 새 설치에서 관측):** 같은
`auto/pro-vision`이 `400 No target in combo auto/pro-vision has confirmed vision support`를
돌려줬다. 콤보가 무엇으로 풀리는지는 그 설치에 연결된 프로바이더에 달려 있기 때문이다.
`/v1/models`를 보면 이유가 분명하다 — **`auto/*` 채널은 `capabilities.vision`을 아예 선언하지
않고**, 구체 모델만 선언한다:

```bash
# 이 게이트웨이에서 이미지를 읽을 수 있는 모델 목록
curl -s http://localhost:20128/v1/models \
  | python3 -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data'] if m.get('capabilities',{}).get('vision')]"
```

**비전 플래그는 주장일 뿐, 동작하는 경로가 아니다 (2026-08-27, 오너 맥 + 이 Pi 양쪽에서 재현):**
`capabilities.vision: true`인 모델이 스크린샷을 그냥 거부한다 —
`400 [400]: DuckDuckGo AI Chat error: ERR_BAD_REQUEST`. 또 다른 경로는 쿼터가 없어서
`429 Error from provider (Console): Rate limit exceeded`. 즉 **목록에서 하나 고르고 끝내면 안 된다.**

그래서 어댑터는 우리가 고른 경로가 실패하면(401 제외 — 인증은 어떤 경로로도 해결되지 않는다)
`/v1/models`를 조회해 비전을 선언한 구체 모델을 **입력 용량 큰 순서로** 최대 3개까지 차례로
시도한다. 성공한 모델은 세션 동안 유지하고, 실패는 이유에 따라 나눠 기억한다:

| 실패 | 처리 |
|------|------|
| 400/404/415/422/501 (페이로드·경로 문제) | 세션 동안 **영구 제외** — 다음 프레임마다 왕복을 낭비하지 않는다 |
| 429·5xx (쿼터·일시 장애) | 이번 호출에서만 건너뛰고 **후보로 유지** — 쿼터는 리셋된다 |
| 401 | 재라우팅 안 함, 어떤 변수를 채우라고 안내 |
| 사용자가 `--model`로 직접 지정 | 재라우팅 안 함 — 그 경로를 고른 건 사용자이므로 오류가 답이다 |

세 개를 다 써도 안 되면 시도 횟수 + 마지막 게이트웨이 이유 + 대시보드 주소를 한 문장으로 말한다.
해설 도중 시각장애인 사용자에게 400 원문이 **음성으로** 읽히는 것은 조치 불가능한 정보이므로,
사람이 모델 목록을 읽고 `--model`을 고르는 대신 게이트웨이에 직접 물어본다. 상한이 3인 이유는
인내심이 아니라 **지연**이다 — 시도마다 해설 턴 안에서 왕복이 한 번 더 붙는다.

라이브 확인(이 Pi, `auto/pro-vision` 기본): 후보 3개(`oc/mimo-v2.5-free` 1.05M →
`aug/gemini-3.1-pro-preview` 1.0M → `ddgw/gpt-5.4-mini` 409k)를 순서대로 시도하고
"모델 3개를 시도했지만 모두 실패했습니다 (마지막 400: ... ERR_BAD_REQUEST)"로 종료.
같은 실패가 다음 프레임에서 되풀이되지 않게, 영구 제외된 경로에서는 다시 시작하지 않는다.

**그 문구가 나왔을 때 무엇을 봐야 하나 — `--list-routes`.** 시도된 후보는 그 게이트웨이에 연결된
프로바이더에 달려 있어서 기계마다 다르다. curl 파이프라인을 손으로 조립하는 대신:

```bash
python scripts/bitgil_demo.py --provider omniroute --list-routes
```

```
게이트웨이 http://localhost:20128/v1 — 콤보 제외 모델 77개
프로바이더별: aug 28개(비전 3), tllm 26개(비전 0), ddgw 6개(비전 3), oc 6개(비전 1), felo 5개(비전 0), ...

비전 선언 모델 7개 (입력 용량 큰 순, → 표시가 실제 시도 순서):
 →  1. oc/mimo-v2.5-free  (1,048,576 tokens)
 →  2. aug/gemini-3.1-pro-preview  (1,000,000 tokens)
 →  3. ddgw/gpt-5.4-mini  (409,600 tokens)
    4. ddgw/gpt-5.4-nano  (409,600 tokens)
```

프로바이더별 집계가 진단의 핵심이다: 어떤 상위 프로바이더가 **카탈로그에 아예 없는지**와
**있지만 비전 플래그가 0인지**를 구분해준다(전자는 대시보드 연결/동기화 문제, 후자는 게이트웨이의
보수적 id 매칭 문제 — [handoff.md](handoff.md) §3-5, §4 참조).

무료 풀은 상위 제공자의 쿼터·egress IP 차단(DuckDuckGo 챌린지, Vercel IP 블록 등)에 걸릴 수
있다. 관측된 무료 풀은 opencode·felo 두 곳뿐이었고, 둘이 죽으면 `auto`와 `auto/best-vision`이
**같은 순서로 같은 실패**를 낸다(`poolSize 11`, `attemptOrder`에 opencode→felo만). 이때 어댑터는
게이트웨이의 원문 오류를 그대로 올린다(`OmniRoute 429: ... Rate limit exceeded`) — 사용자가
원인을 듣고 조치할 수 있어야 하므로 상태코드만 던지지 않는다.
**따라서 이 경로로 해설 품질을 재려면 최소 한 개의 살아있는 비전 라우트가 필요하다**: 실측으로는
게이트웨이 대시보드에서 상위 프로바이더(예: OpenRouter)를 연결하는 것이 유일하게 통한 방법이다.

**인증이 걸린 게이트웨이:** 스코프 토큰을 켰다면 `OMNIROUTE_API_KEY`(게이트웨이 CLI와 같은 변수)
또는 `BITGIL_API_KEY`를 export하면 CLI·웹 서버 양쪽이 자동으로 집어간다. 명시 지정은
`--api-key`. 토큰 없이 401이 나면 어떤 변수를 채워야 하는지 오류 문구가 말해준다(403은 쿼터
소진에도 쓰이므로 인증 힌트를 붙이지 않는다).

## 1. 주요 시나리오 (학습 웨지)

### S1 — 라이브 강의 해설 (F1, `learning-lecture`)
- **목적:** 인강 슬라이드가 넘어갈 때만 증분 해설하고, **보이는 것만** 설명(추측 금지, A3).
- **재현:** `learning-lecture` 프로파일로 서로 다른 슬라이드 프레임을 `/narrate`에 순차 전송.
- **기대/합격 기준:**
  - 동일 프레임 재전송 → `{"changed": false, "reason": "no-change"}` (LLM 미호출, 비용 절감).
  - 다른 프레임 → `{"changed": true}` + 해설.
  - `observe_interval`이 3.0(슬라이드는 천천히 바뀜), `density`는 normal.
  - 프롬프트에 "강사가 가리키는 대상을 **짐작하지 말고** 보이는 것만" 규칙이 있어야 함(A3).

### S2 — 차트/그래프 심층 해설 (F4, `learning-chart`)
- **목적:** 그래프를 구조적으로(종류→축→추세→극값→특이점) 설명하되, **화면에 인쇄되지 않은
  수치를 지어내지 않는다**(A2, 값 오류율 81% 근거).
- **재현:** `learning-chart` 프로파일 로드, 차트 이미지 `/narrate`.
- **기대/합격 기준:**
  - `speed=quality`, `max_image_dim=1600`(축 라벨 가독), `density=detailed`.
  - 프로파일 프롬프트에 "막대 높이·선 위치·축 눈금에서 보간 금지, 못 읽으면 못 읽는다고
    말하기" 하드 규칙이 존재(A2). → `profiles/learning-chart.yaml` 검사.

### S3 — 수식 낭독 (`learning-math`)
- **목적:** 화면의 수식을 보이는 그대로 낭독, **임의 계산·정리·정답 생성 금지**(A2).
- **재현:** `learning-math` 프로파일 로드, 수식 이미지 `/narrate`.
- **기대/합격 기준:** 프롬프트에 "보이는 기호·숫자만, 계산/전개/인수분해 결과를 덧붙이지
  말 것" 규칙 존재. (성숙 스택 MathCAT 위임 재설계는 백로그 E1로 보류.)

### S4 — 복습 노트 내보내기 (F4) — **최고 위험 기능**
- **목적:** 세션 해설을 마크다운 학습물로 내보내되, **기계 생성임을 명시**하고 출처(제공자/
  모델/생성시각)를 붙인다(B1). 사람 검토 전 사실로 오인 금지.
- **재현:** 코어로 직접(오프라인) —
  ```python
  from bitgil_core.review import ReviewLog
  log = ReviewLog(title="1교시", clock=lambda:"10:00", provider="anthropic", model="claude-opus-4-8")
  log.record("슬라이드 1: 제목과 막대그래프.")
  print(log.to_markdown())
  ```
- **기대/합격 기준(자동 검증: `tests/test_review.py`):**
  - 문서 첫머리에 `> ⚠️ 이 노트는 AI가 화면을 보고 자동 생성 …` 고지가 **항상** 존재
    (빈 노트에도).
  - 제공자/모델/생성시각이 알려지면 `> 제공자: … · 모델: … · 생성: …` 출처 줄 표기,
    미상이면 출처 줄 생략(빈 줄만 남기지 않음).

### S5 — 화면에 질문 (F2, Ask the Screen)
- **목적:** 현재 화면에 대한 임의 질문에 답. 데모 프로바이더로 배관만 확인(품질은 실기기).
- **재현:** CLI `python scripts/bitgil_demo.py --image slide.png --ask "제목이 뭐야?"`
  (실 프로바이더 또는 ollama 필요). 배관 자체는 `tests/test_pipeline.py`가 커버.

### S9 — 시험지를 첨부해 대화하는 모드 (문서 직독, `scripts/bitgil_tutor.py`)

- **목적:** 시험지 PDF를 열면 **무슨 시험지인지 먼저 말하고 기다린다.** 지문·선택지는 텍스트
  레이어 원문 그대로(모델 미호출), 도표만 비전, 모델이 말한 숫자는 원문과 대조.
- **어디서 테스트하나:** 지금 이 대화 형태는 **터미널 REPL이 전부다.** `web/server.py`에는
  PDF 업로드 엔드포인트가 없다(`/config`, `/narrate`, `/narrate/stream`, `/triage`,
  `/configure`만). 브라우저에서 파일을 끌어다 놓고 대화하는 화면은 **아직 없는 기능**이다
  (§5 참조). 그래서 키 없이:

  ```bash
  # 대화형 — 열면 개요를 말하고 프롬프트에서 기다린다
  python scripts/bitgil_tutor.py --pdf docs/demo/모의고사_샘플.pdf

  # 스크립트로 한 번에 (여러 번 지정하면 순서대로)
  python scripts/bitgil_tutor.py --pdf docs/demo/모의고사_샘플.pdf \
    --ask "2번 읽어줘" --ask "선택지 다시" --ask "도표 설명해줘"

  # 실 모델로 (도표 설명·물어보기만 왕복한다)
  python scripts/bitgil_tutor.py --pdf 모의고사.pdf --provider bedrock --profile learning-chart
  ```

- **기대/합격 기준:**
  - **첫 응답이 개요**이고 `[원문]`으로 표시되며, **프로바이더 호출이 0회**다(열기만 해도
    비용·환각이 생기면 안 된다). 파일명을 읽지 않고 시험지에 **인쇄된 머리글**을 읽는다.
  - 개요에 문항 수·번호 범위, **도표가 딸린 문항 번호**, 선택지를 못 읽은 문항 번호가 있고,
    마지막이 질문으로 끝나 **학생의 말을 기다린다**(먼저 해설을 시작하지 않는다).
  - `2번 읽어줘` → `[원문 0.0초]`(왕복 없음), 지문 + 선택지 5개.
  - `도표 설명해줘` → `[모델 N초]`, 원문에 없는 숫자가 나오면 `↳ 원문 미확인 숫자:` 고지.
  - `다시` → 직전 응답이 **출처 표시까지 그대로**(모델 답이 `[원문]`으로 바뀌면 결함).
  - 스캔 PDF(텍스트 레이어 없음) → 무엇을 하면 되는지 담긴 한국어 한 문장으로 거부.
  - 자동 검증: `tests/test_tutor.py`, `tests/test_document.py`.

## 2. 안전 시나리오 (인터럽트 트리아지)

프로바이더가 무엇을 답하든 **결정론적 안전 정책**(triage.apply_policy)과 **키워드 휴리스틱**
(safety.augment, 상향만)이 최종 방어선이다. `demo` 프로바이더는 JSON을 주지 않으므로
아래는 **휴리스틱 폴백 경로**를 직접 시험한다(실 LLM 경로는 별도).

### S6 — 스캠(피싱/가짜백신) 팝업
- **재현:** `/triage`에 `{"kind":"dialog","title":"축하합니다!","text":"무료 상품에 당첨…지금 클릭","stole_focus":true}`.
- **기대/합격 기준:** `action=interrupt`, `reason=suspected-scam`, **`needs_confirmation=true`**
  (A1에서 고친 지점 — 스캠 팝업은 대리 클릭 원천 차단 대상), 발화에 "주의: 사기(스캠)" 접두.

### S7 — 보안/권한 프롬프트
- **재현:** `/triage`에 권한 요청 이벤트(예: "이 앱이 카메라에 접근하도록 허용하시겠습니까").
- **기대/합격 기준:** LLM이 분류하면 `is_security_prompt=true` → `interrupt` +
  `needs_confirmation=true`. **휴리스틱 폴백**만으로도 흔한 한국어 권한 문구
  ("권한 요청/접근을 허용/허용하시겠습니까")를 잡아 `needs_confirmation`을 세워야 한다.
  ※ QA에서 이 커버리지 갭을 발견해 보완함(아래 §4 결과 참조).

### S8 — 저가치 알림/광고
- **재현:** `/triage`에 `{"kind":"notification","title":"광고","text":"신상품 세일"}`.
- **기대/합격 기준:** 스캠/보안 신호가 없으면 `queue` 또는 `suppress`(끼어들지 않음). 절대
  조용히 사라지지 않아야 하는 이벤트(포커스 탈취·모달)는 최소 `queue`.

## 3. 회귀·경계 (엔드포인트 계약)

`tests/test_web_server.py`가 자동 검증한다:
- `/narrate` 빈 바디 → HTTP 400. 잘못된 JSON(`/triage`, `/configure`) → HTTP 400.
- `/configure` 미존재 프로파일 → HTTP 400(크래시 금지).
- 경로 탐색(`/../server.py`, `../../etc/passwd`) → 403/404(정적 디렉터리 밖 접근 차단).
- `/narrate/stream` → 문장 단위 텍스트 스트림.

## 4. QA 실행 결과 (최신 라운드)

Pi에서 `demo` 프로바이더로 실행한 결과.

| 시나리오 | 결과 | 비고 |
|---|---|---|
| S1 강의(변화감지) | ✅ | 동일 프레임 no-change, 다른 프레임 change |
| S2 차트 프로파일/규칙 | ✅ | quality/1600/detailed + 반날조 규칙 확인 |
| S3 수식 규칙 | ✅ | 반날조 규칙 확인 |
| S4 복습 노트 고지·출처 | ✅ | 고지 항상 표기, 출처 줄 조건부 |
| S6 스캠 | ✅ | interrupt + needs_confirmation=true |
| S7 보안(LLM 경로) | ✅ | 분류 시 interrupt + 확인 |
| S7 보안(휴리스틱 폴백) | ⚠️→✅ | **갭 발견·보완:** 흔한 권한 문구가 폴백 키워드에 없어 확인 플래그 누락 → 키워드 보강 |
| S8 저가치 알림 | ✅ | queue/suppress |
| §3 엔드포인트 계약 | ✅ | 400/403/404 정상, 스트리밍 정상 |

**이번 라운드에서 코드 점검으로 발견·수정한 결함(회귀 테스트 추가):**

| 영역 | 결함 | 조치 |
|---|---|---|
| triage | 포커스 탈취 `permission_request`가 rule 3(즉시 개입)로 빠지면서 `needs_confirmation`이 안 걸림 | 권한 카테고리는 이 경로에서도 확인 플래그 강제 |
| triage | 스키마 밖 urgency("critical" 등)가 조용히 `suppress`로 드롭 | 명시적 `low`만 억제, 나머지는 `queue`로 표면화 |
| triage | rule 3/4가 요약 없을 때 빈 문자열 발화 | 이벤트 텍스트로 폴백 |
| safety | 흔한 한국어 권한 문구/영문 기술지원 사기 문구 키워드 누락 | 키워드 보강 |
| postprocess | 용어집 치환이 자기 출력물을 재치환(캐스케이드) | 단일 패스 정규식 치환 |
| context | 최근 해설 recap이 라벨("최근순")과 반대로 정렬, 빈 스트림이 빈 불릿 push | 역순 정렬 + 빈 입력 가드 |
| review | 해설에 개행이 섞이면 마크다운 불릿이 쪼개짐 | 내부 공백/개행을 단일 공백으로 축약 |
| profiles | `name` 누락 시 크래시, 잘못된 팩 하나가 전체 로드 중단 | 파일명으로 name 기본값, 손상 파일만 건너뛰기 |
| providers(openai) | 스트리밍 usage-only 청크에서 `choices[0]` IndexError | 빈 choices 청크 skip |
| providers(gemini) | system_instruction이 첫 호출값으로 고정 캐시(트리아지/해설 프롬프트 혼선), `resp.text`가 차단 시 예외 | 프롬프트별 캐시 + `_safe_text` 폴백 |
| web | 경로 검사 `startswith(_STATIC)`가 형제 디렉터리 통과 허용, 잘못된 Content-Length가 500 | 구분자 포함 검사 + 400 + 32MB 상한 |

전 테스트 통과(116개), ruff clean, 시크릿 스캔 clean.

## 5. 아직 검증 못 한 것 (실기기 필요)

- **브라우저에서 시험지를 첨부해 대화하는 화면** — 아직 없는 기능이다. 코어
  (`tutor.TutorSession`)는 UI와 무관하게 완성돼 있지만, 웹으로 노출하려면 업로드 엔드포인트
  (PDF 수신 → `load_pdf` → 세션 보관)와 대화 엔드포인트(`respond`), 그리고 출처 표시
  (`원문`/`모델`)를 화면에도 남기는 UI가 필요하다. 지금 테스트 경로는 S9의 터미널 REPL이다.
- NVDA 실제 음성 출력·SpeechBridge 끼어들기 실배선(Windows 전용).
- OS 이벤트 소스(UIA/토스트)로 트리아지를 실제 구동(현재는 `/triage` curl/향후 소스로만).
- 실 LLM 해설 **품질**(정확도·환각률) — [user-testing.md](user-testing.md)의 오류
  탐지율 실험으로 측정.

## 6. 알려진 제약 (설계상 의도)

- **웹 백엔드는 단일 사용자 프로토타입.** `narrate_stream`은 스트림 전체 구간 동안
  파이프라인 락을 잡는다 — 공유 engine/detector/goal 상태를 두 요청이 교차 변경하지
  못하게 직렬화하려는 의도다(코드 주석 참조). 다중 사용자 서버는 세션마다 별도 engine을
  둬야 하며, 이는 향후 과제다. 지금은 자막/데모/QA 용도라 이 제약이 문제되지 않는다.
