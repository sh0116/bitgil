# 개발 가이드 / Development

## 코어 패키지 개발

```bash
pip install -e ./core[dev]          # 기본 개발 설치
pip install -e ./core[dev,openai]   # 특정 프로바이더 포함
pytest                              # 테스트
ruff check core/                    # 린트
```

코어(`eyemate_core`)는 NVDA에 의존하지 않으므로 일반 파이썬 환경에서 개발·테스트한다.

## 프로토타입 실행 (NVDA 없이) / Try the prototype

애드온과 동일한 코어 파이프라인을 CLI로 실행해 해설 품질을 확인·튜닝할 수 있다.

```bash
# 로컬·오프라인 (Ollama + 비전 모델 필요, 화면이 외부로 안 나감)
python scripts/eyemate_demo.py --image slide.png --provider ollama --model llava

# Anthropic (ANTHROPIC_API_KEY 환경변수 사용)
python scripts/eyemate_demo.py --image chart.png --provider anthropic --profile learning-chart

# 현재 화면 캡처 + 질문 (데스크톱)
python scripts/eyemate_demo.py --screen --ask "내 체력이 얼마야?"

# 스트리밍 낭독
python scripts/eyemate_demo.py --image board.png --profile game-turnbased --stream
```

## 애드온 빌드 / Build the add-on

```bash
python scripts/build_addon.py   # → dist/eyemate-<version>.nvda-addon
```

빌드 스크립트가 MIT 코어(`eyemate_core`)를 `lib/`에 벤더링하고, CC BY 4.0 프로파일 팩을
`profile_packs/`에 번들한다. 산출물 `*.nvda-addon`을 NVDA에서 설치한다.

## NVDA 애드온 빌드

애드온은 `addon/` 아래 NVDA 표준 레이아웃(`manifest.ini`, `globalPlugins/`)을 따른다.
빌드 시 MIT 코어(`eyemate_core`)를 애드온 번들에 포함시킨다.

권장 도구: [NVDA addon templates / SCons 기반 빌드](https://github.com/nvaccess/nvda/blob/master/devDocs/addonInstallation.md).
빌드 스크립트는 M1에서 추가 예정 (TODO).

산출물은 `*.nvda-addon` 파일이며 NVDA의 애드온 스토어 또는 수동 설치로 적용한다.

## 참고 프로젝트
- `cartertemm/AI-content-describer` — 구조·프로바이더 어댑터 참고 (검증된 형태)
- `AAClause/nvda-OpenAI` — 스크린리더 내 LLM 통합 참고
- `nvaccess/nvda` — 애드온 개발 가이드(GPLv2)

## 접근성 자체 요건
애드온 자체가 100% 키보드·음성으로 조작 가능해야 한다("Nothing about us without us").
UI 추가 시 NVDA로 직접 조작 가능한지 반드시 검증할 것.
