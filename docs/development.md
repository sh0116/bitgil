# 개발 가이드 / Development

## 코어 패키지 개발

```bash
pip install -e ./core[dev]          # 기본 개발 설치
pip install -e ./core[dev,openai]   # 특정 프로바이더 포함
pytest                              # 테스트
ruff check core/                    # 린트
```

코어(`eyemate_core`)는 NVDA에 의존하지 않으므로 일반 파이썬 환경에서 개발·테스트한다.

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
