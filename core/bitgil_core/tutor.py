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
_OVERVIEW_WORDS = ("개요", "요약", "몇 문제", "목록", "전체", "어디까지", "몇 개")
# "1번부터 같이 볼까요?"에 대한 학생의 승낙 — 개요를 듣고 첫 문제로 들어가는 말.
_START_WORDS = ("시작", "처음부터", "같이 풀", "같이 보", "함께 풀", "첫 문제")
# 정답을 대신 골라 달라는 요청. 여기에 답을 불러 주면 학습을 대신해 버리고, 듣는 사람은
# 검증할 수 없습니다(모듈 첫머리의 가르치는 태도 참고) — 그래서 코칭으로 되돌립니다.
# "답해줘"(설명 요청)와 섞이지 않도록, '답'만으로는 걸리지 않게 구체적인 어구만 담습니다.
_ANSWER_WORDS = (
	"정답", "답이 뭐", "답은 뭐", "답 뭐", "몇 번이 답", "답 알려", "답 좀",
	"답이야", "답인가", "답일까", "답을 골라", "답 골라",
)

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
		self._last: Optional[TutorReply] = None

	# ---- 상태 ------------------------------------------------------------------

	@property
	def current(self) -> Optional[Question]:
		return self.document.question(self._current) if self._current is not None else None

	def overview(self) -> TutorReply:
		"""**무슨 시험지인지 먼저 말하고 기다립니다** — 시험지를 펼쳤을 때의 첫 응답.

		시험지가 들어오자마자 모델에 넘겨 버리면, 학생이 받는 것은 "AI가 이 시험지에 대해
		한 말" 한 덩어리입니다. 눈으로 보는 학생은 시험지를 펼치면 시험명·과목·문항 수·
		어디에 그림이 있는지를 **한눈에** 먼저 훑고 나서 어디부터 풀지 스스로 정합니다.
		그 첫 훑어보기를 대신하는 것이 이 응답이고, 그래서 여기에는 다음 세 가지 성질이
		있어야 합니다.

		- **LLM을 거치지 않습니다.** 머리글은 원문, 나머지는 문항 목록을 센 결과입니다.
		  시험지를 펼치는 것만으로 왕복 비용이나 환각 위험이 생기지 않습니다.
		- **파일명을 읽지 않습니다.** "모의고사_최종_v3.pdf"는 귀로 듣는 사람에게 정보가
		  아닙니다. 대신 시험지에 인쇄된 머리글(`document.title`)을 읽습니다.
		- **먼저 움직이지 않습니다.** 안내를 끝내면 질문으로 마치고 학생의 말을 기다립니다.
		  무엇을 먼저 들을지는 학생이 정합니다.
		"""
		numbers = [q.number for q in self.document.questions]
		if not numbers:
			return self._reply(
				f"{self.document.path.name}에서 문항 번호를 찾지 못했습니다. "
				"페이지를 직접 읽어 드릴까요? '1쪽 도표 설명해줘'처럼 말해 주세요.",
				grounded=True,
			)
		lines: List[str] = []
		if self.document.title:
			lines.append(self.document.title)
		lines.append(
			f"모두 {len(self.document.pages)}쪽이고, 문항 {len(numbers)}개가 있습니다. "
			f"{numbers[0]}번부터 {numbers[-1]}번까지입니다."
		)
		figures = self.document.figure_numbers()
		if figures:
			lines.append(
				f"도표나 그림이 딸린 문항은 {_listed(figures)}. "
				"이 문항은 그림을 따로 설명해 드립니다."
			)
		choiceless = self.document.choiceless_numbers()
		if choiceless:
			lines.append(
				f"선택지를 읽지 못한 문항은 {_listed(choiceless)}"
				"(서술형이거나 표기가 달라 못 읽은 것일 수 있습니다)."
			)
		lines.append(
			"여기까지는 시험지 원문에서 확인한 것입니다. "
			"어디부터 읽을까요? 문항 번호만 말해도 됩니다."
		)
		return self._reply("\n".join(lines), grounded=True)

	# ---- 1) 원문 낭독 (LLM 없음) -------------------------------------------------

	def read_question(self, number: int) -> TutorReply:
		question = self.document.question(number)
		if question is None:
			return self._reply(self._not_found(number), grounded=True)
		self._current = number
		# 눈으로 보는 학생은 "지금 몇 번째 문제이고, 이제 뭘 할 수 있는지"를 페이지에서
		# 한눈에 압니다. 귀로만 듣는 학생에게는 그 두 가지를 문장으로 얹어 줘야 대화가
		# 이끌리는 느낌이 됩니다. 진행 표시와 다음 행동 안내는 원문을 센 결과·결정론적
		# 안내이므로(개요와 같은 성질) 여전히 grounded=True — 모델을 거치지 않습니다.
		lines = [self._position(number), question.spoken(), self._menu(question)]
		return self._reply("\n".join(p for p in lines if p), grounded=True)

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
		"""직전 응답을 그대로 — **출처 표시까지 그대로.**

		되풀이한 문장이 원문 낭독이었는지 모델의 말이었는지는 반복에서도 유지되어야 합니다.
		여기서 무조건 `grounded=True`를 돌려주면 모델이 한 말이 "원문"으로 다시 읽히는데,
		그 구분이 바로 이 모드가 사용자에게 약속한 것입니다(`scripts/bitgil_tutor.py`의 출처
		표시, 복습 노트의 기계생성 고지와 같은 이유). 복습 노트에는 다시 기록하지 않습니다 —
		같은 문장을 두 번 들은 것이 학습 기록상 두 번 일어난 일은 아닙니다.
		"""
		if self._last is None:
			return self.overview()
		return self._last

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
		# 화면 해설과 같은 후처리(용어집 치환 + 길이 상한)를 자유 답변에도 적용합니다.
		# 이걸 건너뛰면 "HP" 같은 용어가 도표 설명에서만 "체력"으로 읽히고 물어보기에서는
		# 안 읽히는 식으로 두 경로가 어긋납니다.
		finished = self.engine._finish(resp.text.strip())
		text, missing = annotate_unsupported(finished, [source])
		return self._reply(text, grounded=False, unsupported=missing)

	# ---- 4) 코칭 (정답을 대신 고르지 않기) ----------------------------------------

	def coach_answer(self) -> TutorReply:
		"""정답을 물으면 답 대신 **어떻게 접근할지**로 되돌립니다.

		답을 그냥 불러 주면 학습을 대신해 버리고, 듣는 사람은 검증할 수 없습니다
		(BLV 사용자는 AI 오류를 약 50%만 잡아냅니다). 그래서 정답 요청은 모델로 넘기지
		않고 — 넘겨도 `TUTOR_PROMPT`가 거절하지만, 결정론적으로 처리하면 더 빠르고 확실합니다 —
		무엇을 해 볼 수 있는지 안내합니다. 안내이므로 grounded=True(모델 없음).
		"""
		question = self.current
		lines = ["정답은 제가 대신 골라 드리지 않아요. 직접 고를 때 실력이 됩니다."]
		if question is not None and question.choices:
			lines.append(
				"대신 선택지 하나하나가 무슨 뜻인지, 원문의 어디가 단서인지 짚어 드릴게요. "
				"'선택지'라고 하면 다시 읽어 드리고, '이 문제가 뭘 묻는지' 물으면 원문만 근거로 설명합니다."
			)
		else:
			lines.append(
				"대신 이 문제가 무엇을 묻는지, 원문의 어디가 단서인지 짚어 드릴게요. "
				"'이 문제가 뭘 묻는지'라고 물어보세요."
			)
		return self._reply("\n".join(lines), grounded=True)

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
		# "1번부터 같이 볼까요?"에 "시작"이라고 답하면 첫 문제로 들어간다.
		if _has(lowered, _START_WORDS):
			return self._first()
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
		# "4번이 답이야?"처럼 정답을 물으면 문항 지목은 반영하되 답 대신 코칭으로 되돌린다.
		# 지목 뒤에 답을 묻는 말이 붙으므로 낭독(is_bare)이 아니라 여기서 먼저 가로챈다.
		if _has(lowered, _ANSWER_WORDS):
			ref, _ = _question_ref(text)
			if ref is not None and self.document.question(ref):
				self._current = ref
			return self.coach_answer()
		number, is_bare = _question_ref(text)
		if number is not None and is_bare:
			# "3번" / "3번 문제 읽어줘"처럼 지목만 하는 발화는 낭독. 뒤에 질문이 붙어
			# 있으면(예: "3번은 뭘 묻는 거야") 지목만 하고 질문으로 넘깁니다.
			return self.read_question(number)
		if number is not None:
			self._current = number if self.document.question(number) else self._current
		return self.ask(text)

	# ---- 내부 ------------------------------------------------------------------

	def _first(self) -> TutorReply:
		numbers = [q.number for q in self.document.questions]
		if not numbers:
			return self.overview()
		return self.read_question(numbers[0])

	def _position(self, number: int) -> str:
		"""'3문항 중 2번째입니다.' — 지금 어디쯤인지. 목록에 없으면 빈 문자열."""
		numbers = [q.number for q in self.document.questions]
		if number not in numbers:
			return ""
		return f"{len(numbers)}문항 중 {numbers.index(number) + 1}번째입니다."

	def _menu(self, question: Question) -> str:
		"""이 문항에서 **실제로 할 수 있는 것만** 골라 다음 행동을 안내합니다.

		선택지가 없는 문항에 "선택지", 그림이 없는 문항에 "도표 설명"을 권하면 안내가
		거짓이 됩니다 — 있는 것만 담습니다. 각 항목은 라우터가 알아듣는 말이라, 학생이
		그대로 따라 말하면 바로 동작합니다.
		"""
		numbers = [q.number for q in self.document.questions]
		options: List[str] = []
		if question.choices:
			options.append("선택지 다시 듣기")
		if question.number in self.document.figure_numbers():
			options.append("도표 설명 듣기")
		options.append("이 문제가 뭘 묻는지 물어보기")
		if question.number in numbers and numbers.index(question.number) < len(numbers) - 1:
			options.append("다음 문제로 가기")
		return ", ".join(options) + " — 무엇이든 말해 주세요."

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
		reply = TutorReply(text=text, grounded=grounded, unsupported=unsupported or [])
		self._last = reply
		if self.review_log is not None:
			self.review_log.record(text)
		return reply


# 한 번에 읽어 줄 번호 개수 상한. 스무 개를 줄줄이 읽는 것은 안내가 아니라 소음입니다 —
# 개수만 알려주고 나머지는 학생이 지목할 때 읽습니다.
_LISTED_MAX = 8


def _listed(numbers: List[int]) -> str:
	"""번호 목록을 낭독용 서술어로 ("2번, 3번입니다" / "… 등 모두 20개입니다"). 마침표는 부르는 쪽에서."""
	shown = ", ".join(f"{n}번" for n in numbers[:_LISTED_MAX])
	if len(numbers) <= _LISTED_MAX:
		return f"{shown}입니다"
	return f"{shown} 등 모두 {len(numbers)}개입니다"


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
