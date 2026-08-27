"""TutorSession — 시험지를 함께 푸는 대화 루프(문서 직독 모드).

시각장애 학생이 모의고사를 풀 때 실제로 필요한 것은 "화면 설명"이 아니라 **원문을 정확히,
원하는 단위로 다시 들을 수 있는 것**입니다. 그래서 이 세션은 세 갈래로 나뉩니다.

1. 지문·선택지 낭독 — `document.py`의 텍스트 레이어에서 그대로. **LLM을 거치지 않습니다.**
   여기서 환각은 구조적으로 불가능하고, 왕복이 없으니 즉시 응답합니다.
2. 도표·그림 설명 — 페이지를 렌더링해 비전 모델로. 원문에 없는 숫자는 `factcheck`가
   고지를 붙입니다.
3. 물어보기 — 학생의 질문에 답하되, **근거는 그 문항의 원문으로 한정**합니다. 원문에
   없으면 지어내지 않고 없다고 말합니다.

가르치는 태도에 대한 결정: **정답을 대신 판정하지 않습니다.** 답을 그냥 불러 주면 듣는
사람은 검증할 수 없고(BLV 사용자는 AI 오류를 약 50%만 잡아냅니다), 학습 자체를 대신해
버립니다 — 백로그 D1이 아동 프로토콜에서 재려는 바로 그 위험입니다. 무엇을 묻는 문제인지,
어떤 단서가 원문에 있는지까지 안내하고 판단은 학생에게 남깁니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .document import ExamDocument, Question
from .engine import NarrationEngine
from .factcheck import annotate_unsupported
from .providers.base import Message
from .review import ReviewLog

# 물어보기(3번 갈래)의 시스템 프롬프트. 화면 캡처용 프로파일 프롬프트와 달리 **이미지가
# 없다**는 전제이므로, 근거를 원문 문자열로 못박는 것이 핵심입니다.
TUTOR_PROMPT = """당신은 시각장애 학생과 함께 시험지를 읽는 과외 선생님입니다.
아래에 주어진 '문항 원문'만을 근거로 답하세요.

지켜야 할 것:
- 원문에 없는 내용·수치는 절대 지어내지 마세요. 없으면 "원문에 나와 있지 않습니다"라고
  말하고, 어디를 확인하면 되는지 알려주세요.
- 정답을 대신 판정하지 마세요. 이 문제가 무엇을 묻는지, 원문의 어떤 부분이 단서인지까지
  안내하고 판단은 학생에게 남기세요.
- 학생이 정답을 직접 물어도, 답을 고르는 근거가 되는 원문 부분을 짚어 주는 것으로
  답하세요.
- 귀로만 듣는 사람에게 말하듯, 짧은 문장으로 순서대로 말하세요. 표나 기호를 그리지 마세요.
"""

_FIGURE_WORDS = ("도표", "그래프", "그림", "차트", "표를", "지도", "사진")
_CHOICE_WORDS = ("선택지", "보기", "답지")
_NEXT_WORDS = ("다음", "그다음", "넘어가")
_PREV_WORDS = ("이전", "앞 문제", "전 문제", "돌아가")
_REPEAT_WORDS = ("다시", "한 번 더", "반복")
_OVERVIEW_WORDS = ("몇 문제", "목록", "전체", "어디까지", "몇 개")

# "3번", "3번 문제", "문 3", "3번문제" — 문항 지목.
_QUESTION_REF = re.compile(r"(?:문\s*)?(\d{1,2})\s*번?\s*(?:문제)?")


@dataclass
class TutorReply:
	"""한 번의 응답. `grounded`는 LLM을 거치지 않은 원문 낭독인지 여부입니다."""

	text: str
	grounded: bool = False
	unsupported: Optional[List[str]] = None

	def __str__(self) -> str:  # CLI/웹이 그대로 낭독할 수 있게
		return self.text


class TutorSession:
	def __init__(
		self,
		document: ExamDocument,
		engine: NarrationEngine,
		review_log: Optional[ReviewLog] = None,
		render_dpi: int = 150,
	):
		self.document = document
		self.engine = engine
		self.review_log = review_log
		self.render_dpi = render_dpi
		self._current: Optional[int] = None
		self._last: str = ""

	# ---- 상태 ------------------------------------------------------------------

	@property
	def current(self) -> Optional[Question]:
		return self.document.question(self._current) if self._current is not None else None

	def overview(self) -> TutorReply:
		"""문서에 문항이 몇 개 있고 어디부터 어디까지인지 — 첫 방향 감각."""
		numbers = [q.number for q in self.document.questions]
		if not numbers:
			return self._reply(
				f"{self.document.path.name}에서 문항 번호를 찾지 못했습니다. "
				"페이지를 직접 읽어 드릴까요? '1쪽 도표 설명해줘'처럼 말해 주세요.",
				grounded=True,
			)
		return self._reply(
			f"{self.document.path.name}, {len(self.document.pages)}쪽에 문항 "
			f"{len(numbers)}개가 있습니다. {numbers[0]}번부터 {numbers[-1]}번까지입니다. "
			"'3번 읽어줘'처럼 말해 주세요.",
			grounded=True,
		)

	# ---- 1) 원문 낭독 (LLM 없음) -------------------------------------------------

	def read_question(self, number: int) -> TutorReply:
		question = self.document.question(number)
		if question is None:
			return self._reply(self._not_found(number), grounded=True)
		self._current = number
		return self._reply(question.spoken(), grounded=True)

	def read_choices(self) -> TutorReply:
		question = self.current
		if question is None:
			return self._reply("먼저 몇 번 문제인지 말해 주세요.", grounded=True)
		if not question.choices:
			return self._reply(
				f"{question.number}번은 선택지가 원문에서 확인되지 않습니다"
				"(서술형이거나 표기가 달라 못 읽은 것일 수 있습니다).",
				grounded=True,
			)
		listed = "\n".join(
			f"{i}번, {c}" for i, c in enumerate(question.choices, start=1)
		)
		return self._reply(f"{question.number}번 선택지입니다.\n{listed}", grounded=True)

	def step(self, delta: int) -> TutorReply:
		"""다음/이전 문항으로. 목록 순서를 따르므로 번호가 띄어져 있어도 동작합니다."""
		numbers = [q.number for q in self.document.questions]
		if not numbers:
			return self.overview()
		if self._current is None:
			return self.read_question(numbers[0])
		index = numbers.index(self._current) if self._current in numbers else 0
		target = index + delta
		if target < 0:
			return self._reply("첫 문제입니다.", grounded=True)
		if target >= len(numbers):
			return self._reply("마지막 문제입니다.", grounded=True)
		return self.read_question(numbers[target])

	def repeat(self) -> TutorReply:
		if not self._last:
			return self.overview()
		return TutorReply(text=self._last, grounded=True)

	# ---- 2) 도표 설명 (비전 + 수치 대조) ------------------------------------------

	def describe_figure(self, page: Optional[int] = None) -> TutorReply:
		"""페이지를 렌더링해 비전 모델로 설명하고, 원문에 없는 숫자에 고지를 붙입니다.

		근거로 대조하는 원문은 **그 페이지 전체 텍스트**입니다(문항 원문만 쓰면 축 라벨처럼
		문항 밖에 인쇄된 값이 근거 없다고 잘못 표시됩니다).
		"""
		if page is None:
			page = self.current.page if self.current else 0
		question = self.current
		ask = "이 페이지의 도표·그림을 시각장애 학생에게 설명해 주세요."
		if question is not None:
			ask = f"{question.number}번 문제에 딸린 도표·그림을 설명해 주세요. " + ask
		frame = self.document.render_page(page, dpi=self.render_dpi)
		narration = self.engine.narrate(frame, question=ask).text
		text, missing = annotate_unsupported(narration, [self.document.page_text(page)])
		return self._reply(text, grounded=False, unsupported=missing)

	# ---- 3) 물어보기 (원문 근거 한정) ---------------------------------------------

	def ask(self, utterance: str) -> TutorReply:
		"""학생의 질문에 그 문항 원문만을 근거로 답합니다(이미지 없음 → 빠르고 쌉니다)."""
		question = self.current
		if question is None:
			return self._reply(
				"먼저 몇 번 문제를 볼지 말해 주세요. 예를 들어 '3번 읽어줘'입니다.",
				grounded=True,
			)
		source = question.source_text()
		messages = [
			Message(role="system", text=TUTOR_PROMPT),
			Message(role="system", text=f"문항 원문:\n{source}"),
			Message(role="user", text=utterance),
		]
		resp = self.engine.provider.complete(messages, max_tokens=400)
		text, missing = annotate_unsupported(resp.text.strip(), [source])
		return self._reply(text, grounded=False, unsupported=missing)

	# ---- 의도 라우팅 --------------------------------------------------------------

	def respond(self, utterance: str) -> TutorReply:
		"""말이든 타자든 한 줄이 들어오면 알맞은 갈래로 보냅니다.

		규칙 기반입니다 — 의도 분류에까지 LLM 왕복을 넣으면 "3번 읽어줘"처럼 결정론적으로
		처리할 수 있는 요청조차 느려지고, 분류가 틀릴 여지가 생깁니다.
		"""
		text = utterance.strip()
		if not text:
			return self.overview()
		lowered = text.lower()
		if _has(lowered, _OVERVIEW_WORDS):
			return self.overview()
		# 무엇을 다시 들려줄지가 먼저다. "선택지 다시 말해줘"는 반복이 아니라 선택지 낭독이고,
		# 반복을 앞에 두면 직전 응답(지문)을 되풀이해 엉뚱한 걸 읽는다.
		if _has(lowered, _CHOICE_WORDS):
			return self.read_choices()
		if _has(lowered, _FIGURE_WORDS):
			return self.describe_figure(_page_ref(text))
		if _has(lowered, _NEXT_WORDS):
			return self.step(1)
		if _has(lowered, _PREV_WORDS):
			return self.step(-1)
		if _has(lowered, _REPEAT_WORDS):
			return self.repeat()
		number, is_bare = _question_ref(text)
		if number is not None and is_bare:
			# "3번" / "3번 문제 읽어줘"처럼 지목만 하는 발화는 낭독. 뒤에 질문이 붙어
			# 있으면(예: "3번은 뭘 묻는 거야") 지목만 하고 질문으로 넘깁니다.
			return self.read_question(number)
		if number is not None:
			self._current = number if self.document.question(number) else self._current
		return self.ask(text)

	# ---- 내부 ------------------------------------------------------------------

	def _not_found(self, number: int) -> str:
		numbers = [q.number for q in self.document.questions]
		if not numbers:
			return f"{number}번을 찾지 못했습니다. 이 문서에서 문항 번호를 읽지 못했습니다."
		return (
			f"{number}번은 이 문서에 없습니다. "
			f"{numbers[0]}번부터 {numbers[-1]}번까지 있습니다."
		)

	def _reply(
		self, text: str, grounded: bool, unsupported: Optional[List[str]] = None
	) -> TutorReply:
		self._last = text
		if self.review_log is not None:
			self.review_log.record(text)
		return TutorReply(text=text, grounded=grounded, unsupported=unsupported or [])


def _has(lowered: str, words: Tuple[str, ...]) -> bool:
	return any(w in lowered for w in words)


def _question_ref(text: str) -> Tuple[Optional[int], bool]:
	"""(문항 번호, 지목만 하는 발화인지). 번호가 없으면 (None, False)."""
	match = _QUESTION_REF.search(text)
	if match is None:
		return None, False
	# 지목 뒤에 남는 말이 낭독 요청뿐이면 '지목만'으로 봅니다.
	rest = (text[: match.start()] + text[match.end():]).strip()
	bare = all(
		token in ("읽어줘", "읽어", "읽어주세요", "읽어 줘", "알려줘", "문제", "번", "가자", "으로")
		for token in rest.split()
	)
	return int(match.group(1)), bare


def _page_ref(text: str) -> Optional[int]:
	"""'2쪽 도표'처럼 쪽을 지정했으면 0-기반 인덱스로. 없으면 None(현재 문항 쪽)."""
	match = re.search(r"(\d{1,3})\s*(?:쪽|페이지)", text)
	return int(match.group(1)) - 1 if match else None
