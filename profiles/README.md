# EyeMate 프로파일 팩 / Profile Packs

프로파일은 특정 게임이나 학습 플랫폼에 맞춰 EyeMate의 해설 방식을 조정하는 **YAML 설정**
입니다. 코드를 고치지 않고 데이터만 바꿔 대응하므로, 게임이 업데이트되어 화면이 바뀌어도
프로파일만 손보면 됩니다. **비개발자(시각장애인 당사자 포함)도 기여할 수 있습니다.**

## 내장 프로파일 / Built-in profiles

| 파일 | 도메인 | 용도 |
|------|--------|------|
| `general.yaml` | general | 범용 기본값 |
| `game-turnbased.yaml` | game-turnbased | 턴제·카드 게임 (Slay the Spire류) |
| `game-realtime.yaml` | game-realtime | 실시간 게임 (향후 과제, 초간결 해설) |
| `learning-lecture.yaml` | learning-lecture | 강의 영상 (슬라이드 전환 감지) |
| `learning-chart.yaml` | learning-chart | 그래프·차트·도표 심층 설명 |
| `learning-math.yaml` | learning-math | 수식 자연어 낭독 |

## 필드 / Fields

| 필드 | 설명 |
|------|------|
| `name` | 고유 이름 |
| `domain` | 도메인 분류 |
| `language` | 언어 코드 (다국어 확장용) |
| `system_prompt` | 무엇에 집중해 해설할지 지시하는 프롬프트 |
| `glossary` | 용어 → 한국어 독음 치환 사전 |
| `roi` | 관심 영역 힌트 (체력바 위치 등), 0~1 비율 `[x, y, w, h]` |
| `hash_threshold` | 변화 감지 민감도 (실시간 게임은 높게) |
| `use_ocr` | OCR 텍스트 diff 사용 여부 |
| `narration_density` | `brief` / `normal` / `detailed` |

## 기여 / Contributing

커뮤니티 프로파일 팩은 별도 저장소 `eyemate-profiles`에 PR로 기여합니다.
"이 게임의 해설이 이상하다"는 이슈 자체가 훌륭한 기여입니다.

라이선스: **CC BY 4.0** (see [LICENSE](LICENSE)).
