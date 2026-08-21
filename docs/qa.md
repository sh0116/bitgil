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

- NVDA 실제 음성 출력·SpeechBridge 끼어들기 실배선(Windows 전용).
- OS 이벤트 소스(UIA/토스트)로 트리아지를 실제 구동(현재는 `/triage` curl/향후 소스로만).
- 실 LLM 해설 **품질**(정확도·환각률) — [user-testing.md](user-testing.md)의 오류
  탐지율 실험으로 측정.

## 6. 알려진 제약 (설계상 의도)

- **웹 백엔드는 단일 사용자 프로토타입.** `narrate_stream`은 스트림 전체 구간 동안
  파이프라인 락을 잡는다 — 공유 engine/detector/goal 상태를 두 요청이 교차 변경하지
  못하게 직렬화하려는 의도다(코드 주석 참조). 다중 사용자 서버는 세션마다 별도 engine을
  둬야 하며, 이는 향후 과제다. 지금은 자막/데모/QA 용도라 이 제약이 문제되지 않는다.
