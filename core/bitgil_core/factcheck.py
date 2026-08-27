"""수치 대조 — 모델이 말한 숫자가 원문에 실제로 인쇄되어 있는지 확인하는 결정론적 백스톱.

프로파일 프롬프트는 이미 "화면에 인쇄된 값만 말하라"고 지시합니다(`profiles/learning-chart.yaml`).
하지만 프롬프트는 부탁이고, 값 오류는 차트 캡션 오류 중 1위입니다([docs/evidence.md]).
그래서 부탁을 믿지 않고 나가는 문장을 한 번 더 검사합니다 — `safety.py`가 LLM 분류를
결정론적 규칙으로 **상향만** 보정하는 것과 같은 자리입니다.

원문(PDF 텍스트 레이어, OCR 결과)에 없는 숫자가 해설에 나오면 지우지 않고 **고지를 붙입니다.**
지우면 문장의 뜻이 바뀌고, 사용자는 무엇이 사라졌는지조차 알 수 없습니다. 판단에 필요한
것은 "이 숫자는 원문에서 확인되지 않았다"는 사실이고, 그건 말해 줄 수 있습니다.

**이 검사의 한계(과대평가 금지):** 숫자가 지어내진 것인지만 봅니다.
- 인쇄된 숫자를 쓰면서 **관계**를 틀리게 말하는 것(어느 막대가 가장 높은지 뒤집기)은
  잡지 못합니다.
- 값 대조이므로 "4개"의 4가 원문의 "4번"으로 뒷받침되는 것도 통과합니다.
- "1번 선택지", "2쪽"처럼 **우리가 낭독을 위해 붙인 탐색 번호는 검사하지 않습니다.**
  원문에 없는 게 당연해서, 검사하면 고지가 소음이 되고 정작 지어낸 값이 묻힙니다.
- 같은 이유로 모델이 답을 구조화하려고 줄 앞에 붙인 목록 번호("5) 전반적인 추세")도
  검사에서 뺍니다.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set, Tuple

# 1,200 / 3.5 / 42 — 천 단위 쉼표와 소수점을 한 토큰으로 봅니다.
# 뒤에 붙는 탐색용 단위(번/쪽/번째…)는 검사에서 빼기 위해 함께 잡습니다.
_NUMBER = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(번째|번|쪽|페이지|째)?")

# 줄 맨 앞의 목록 번호("3) 축 정보", "4. 주요 특징"). 모델이 답을 구조화하려고 붙인 번호이고
# 화면에 대한 주장이 아닙니다. 실측에서 "5) 전반적인 추세"의 5가 근거 없는 숫자로 잡혀
# 고지가 소음이 됐습니다 — 고지를 못 믿게 되면 정작 지어낸 값도 함께 무시됩니다.
#
# 두 자리까지만 목록 번호로 봅니다. 값이 줄 맨 앞에 오고 마침표가 뒤따르면("155. 이것이…")
# 목록 번호와 형태가 같아서 원리적으로 구분할 수 없는데, 그 모호함을 세 자리 이상까지
# 넓히면 지어낸 값을 놓치는 쪽의 손해가 커집니다.
_LIST_MARKER = re.compile(r"^[\s\-•*]*\(?\d{1,2}[).](?=\s)", re.MULTILINE)


def numbers_in(text: str, *, all_tokens: bool = False) -> List[str]:
	"""텍스트에 나타난 숫자 토큰을 등장 순서대로 (원문 표기 그대로) 반환.

	기본값은 **탐색용 번호를 뺍니다** — "1번 선택지", "2쪽"의 숫자는 우리가 낭독을 위해
	직접 붙인 것이어서 원문에 없는 게 당연하고, 이걸 고지하면 고지가 소음이 됩니다.
	`all_tokens=True`면 그런 번호까지 포함해 그대로 돌려줍니다.
	"""
	found = _NUMBER.findall(text or "")
	return [num for num, unit in found if all_tokens or not unit]


def _values(text: str, *, all_tokens: bool = True) -> Set[float]:
	"""숫자 토큰을 값으로 정규화 — "1,200"과 "1200", "12"와 "12.0"을 같게 봅니다.

	근거(원문) 쪽은 `all_tokens=True`로 넓게 모읍니다. 원문의 "1번"이 해설의 "1"을
	뒷받침하지 못하면 오탐이 늘어날 뿐이고, 근거를 넓게 인정하는 방향의 오차는
	"지어냈다고 잘못 몰아세우지 않는" 쪽이라 안전합니다.
	"""
	out: Set[float] = set()
	for token in numbers_in(text, all_tokens=all_tokens):
		try:
			out.add(float(token.replace(",", "")))
		except ValueError:  # pragma: no cover - 정규식이 통과시킨 것만 오므로 방어용
			continue
	return out


def unsupported_numbers(narration: str, sources: Sequence[str] | Iterable[str]) -> List[str]:
	"""해설에는 있고 원문 어디에도 없는 숫자를, 해설에 나온 표기대로 중복 없이 반환."""
	supported: Set[float] = set()
	for source in sources:
		supported |= _values(source)
	unsupported: List[str] = []
	seen: Set[float] = set()
	checked = _LIST_MARKER.sub("", narration or "")
	for token in numbers_in(checked, all_tokens=False):
		try:
			value = float(token.replace(",", ""))
		except ValueError:  # pragma: no cover
			continue
		if value in supported or value in seen:
			continue
		seen.add(value)
		unsupported.append(token)
	return unsupported


def annotate_unsupported(
	narration: str, sources: Sequence[str] | Iterable[str]
) -> Tuple[str, List[str]]:
	"""(고지가 붙은 해설, 확인되지 않은 숫자 목록).

	근거 없는 숫자가 없으면 원문을 그대로 돌려줍니다 — 문제가 없을 때 조용한 것이
	낭독 도구의 기본값이어야 합니다.
	"""
	missing = unsupported_numbers(narration, sources)
	if not missing:
		return narration, []
	listed = ", ".join(missing)
	notice = (
		f"확인 필요: {listed}은(는) 원문에서 확인되지 않은 숫자입니다. "
		"화면의 라벨을 직접 확인해 주세요."
	)
	return f"{narration.rstrip()}\n{notice}", missing
