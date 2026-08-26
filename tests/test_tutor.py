"""Tests for TutorSession — 시험지를 함께 푸는 대화 루프.

The provider is a fake and pages are never rendered from a real PDF (the document
is constructed directly), so these run offline and without poppler.
"""

import pytest

from bitgil_core.document import ExamDocument, Question
from bitgil_core.engine import NarrationEngine
from bitgil_core.profiles import Profile
from bitgil_core.providers.base import VisionProvider, VisionResponse
from bitgil_core.review import ReviewLog
from bitgil_core.tutor import TutorSession


class FakeProvider(VisionProvider):
	"""Records the messages it was called with and returns canned text."""

	name = "fake"

	def __init__(self, reply="막대 네 개가 있습니다."):
		self.reply = reply
		self.last_messages = None
		self.calls = 0

	def complete(self, messages, *, max_tokens=300):
		self.last_messages = list(messages)
		self.calls += 1
		return VisionResponse(text=self.reply, prompt_tokens=7, completion_tokens=5)


class FakeDocument(ExamDocument):
	"""ExamDocument whose page rendering is a stub — no poppler, no real PDF."""

	def render_page(self, index, dpi=150):
		self.rendered = (index, dpi)
		return b"\x89PNG-fake"


def _session(reply="막대 네 개가 있습니다.", review_log=None):
	doc = FakeDocument(
		path=type("P", (), {"name": "모의고사.pdf"})(),
		pages=["1. 다음 표는 월별 판매량이다. 1월 120, 4월 260"],
		questions=[
			Question(number=1, stem="다음 표의 최고점은?", choices=["1월", "4월"], page=0),
			Question(number=2, stem="증가 추세인가?", choices=[], page=0),
		],
	)
	provider = FakeProvider(reply)
	engine = NarrationEngine(provider, Profile(name="t", system_prompt="s"))
	return TutorSession(doc, engine, review_log=review_log), provider, doc


# --- 원문 낭독은 LLM을 거치지 않는다 ---------------------------------------------

def test_read_question_never_calls_the_model():
	session, provider, _ = _session()
	reply = session.read_question(1)
	assert provider.calls == 0          # 이 경로에서 환각은 구조적으로 불가능
	assert reply.grounded is True
	assert "1번. 다음 표의 최고점은?" in reply.text
	assert "1번 선택지, 1월" in reply.text


def test_read_choices_lists_them_numbered():
	session, provider, _ = _session()
	session.read_question(1)
	reply = session.read_choices()
	assert provider.calls == 0
	assert "1번, 1월" in reply.text and "2번, 4월" in reply.text


def test_read_choices_before_picking_a_question_asks_which_one():
	session, _, _ = _session()
	assert "몇 번" in session.read_choices().text


def test_read_choices_for_a_written_answer_question_says_so():
	session, _, _ = _session()
	session.read_question(2)
	assert "선택지가 원문에서 확인되지 않습니다" in session.read_choices().text


def test_missing_question_reports_the_available_range():
	session, _, _ = _session()
	text = session.read_question(9).text
	assert "9번은 이 문서에 없습니다" in text
	assert "1번부터 2번까지" in text


# --- 이동 ----------------------------------------------------------------------

def test_step_moves_forward_and_reports_the_last_one():
	session, _, _ = _session()
	session.read_question(1)
	assert "2번." in session.step(1).text
	assert session.step(1).text == "마지막 문제입니다."


def test_step_backward_stops_at_the_first():
	session, _, _ = _session()
	session.read_question(1)
	assert session.step(-1).text == "첫 문제입니다."


def test_step_without_a_current_question_opens_the_first():
	session, _, _ = _session()
	assert "1번." in session.step(1).text


def test_repeat_returns_the_previous_reply():
	session, _, _ = _session()
	first = session.read_question(1).text
	assert session.repeat().text == first


def test_repeat_before_anything_gives_the_overview():
	session, _, _ = _session()
	assert "문항 2개" in session.repeat().text


def test_overview_counts_questions_and_pages():
	session, _, _ = _session()
	text = session.overview().text
	assert "문항 2개" in text and "1번부터 2번까지" in text


def test_overview_without_questions_offers_the_page_route():
	doc = FakeDocument(path=type("P", (), {"name": "x.pdf"})(), pages=["본문"], questions=[])
	engine = NarrationEngine(FakeProvider(), Profile(name="t"))
	assert "문항 번호를 찾지 못했습니다" in TutorSession(doc, engine).overview().text


# --- 도표 설명: 비전 + 수치 대조 --------------------------------------------------

def test_describe_figure_renders_the_current_page_and_calls_the_model():
	session, provider, doc = _session()
	session.read_question(1)
	reply = session.describe_figure()
	assert doc.rendered == (0, 150)
	assert provider.calls == 1
	assert reply.grounded is False


def test_describe_figure_flags_a_number_absent_from_the_page():
	# 원문에는 120과 260만 인쇄돼 있는데 모델이 155를 말하면 고지가 붙어야 한다.
	session, _, _ = _session(reply="라벨 없는 막대는 155로 보입니다.")
	session.read_question(1)
	reply = session.describe_figure()
	assert reply.unsupported == ["155"]
	assert "확인되지 않은 숫자" in reply.text


def test_describe_figure_keeps_quiet_when_numbers_check_out():
	session, _, _ = _session(reply="4월이 260으로 가장 높습니다.")
	session.read_question(1)
	reply = session.describe_figure()
	assert reply.unsupported == []
	assert "확인 필요" not in reply.text


def test_describe_figure_uses_page_text_not_just_the_question():
	# 축 라벨(120)은 문항 지문 밖에 인쇄돼 있다 — 근거를 문항으로만 좁히면 오탐한다.
	session, _, _ = _session(reply="1월은 120입니다.")
	session.read_question(1)
	assert session.describe_figure().unsupported == []


# --- 물어보기: 근거는 문항 원문으로 한정 -------------------------------------------

def test_ask_grounds_the_prompt_on_the_question_source():
	session, provider, _ = _session(reply="무엇을 묻는지 설명합니다.")
	session.read_question(1)
	session.ask("이 문제 뭘 묻는 거야?")
	texts = [m.text for m in provider.last_messages]
	assert any("과외 선생님" in t for t in texts)
	assert any("다음 표의 최고점은?" in t for t in texts)
	assert all(m.image is None for m in provider.last_messages)   # 텍스트만 → 빠르고 싸다


def test_ask_before_picking_a_question_asks_which_one():
	session, provider, _ = _session()
	assert "3번 읽어줘" in session.ask("이거 뭐야?").text
	assert provider.calls == 0


def test_ask_flags_a_fabricated_number_in_the_answer():
	session, _, _ = _session(reply="근거가 되는 값은 155입니다.")
	session.read_question(1)
	assert session.ask("답이 뭐야?").unsupported == ["155"]


# --- 의도 라우팅 ----------------------------------------------------------------

@pytest.mark.parametrize(
	"utterance,expected",
	[
		("3번 읽어줘", "없습니다"),          # 3번은 없음 → 범위 안내
		("1번", "1번."),
		("1번 문제 읽어줘", "1번."),
		("문 2", "2번."),
	],
)
def test_respond_routes_a_bare_reference_to_reading(utterance, expected):
	session, provider, _ = _session()
	assert expected in session.respond(utterance).text
	assert provider.calls == 0


def test_respond_routes_a_question_about_an_item_to_the_model():
	session, provider, _ = _session(reply="이 문제는 최고점을 묻습니다.")
	session.respond("1번은 뭘 묻는 거야?")
	assert provider.calls == 1
	assert session.current.number == 1        # 지목은 반영되어야 한다


def test_respond_routes_figure_words_to_the_vision_path():
	session, provider, doc = _session()
	session.read_question(1)
	session.respond("도표 설명해줘")
	assert provider.calls == 1 and doc.rendered == (0, 150)


def test_respond_honours_an_explicit_page_for_a_figure():
	session, _, doc = _session()
	session.respond("2쪽 그래프 설명해줘")
	assert doc.rendered == (1, 150)


def test_respond_routes_choice_words_without_the_model():
	session, provider, _ = _session()
	session.read_question(1)
	assert "1번, 1월" in session.respond("선택지 다시 말해줘").text
	assert provider.calls == 0


def test_respond_routes_next_and_previous():
	session, _, _ = _session()
	session.read_question(1)
	assert "2번." in session.respond("다음 문제").text
	assert "1번." in session.respond("이전 문제").text


def test_respond_empty_utterance_gives_the_overview():
	session, _, _ = _session()
	assert "문항 2개" in session.respond("   ").text


def test_respond_overview_words():
	session, _, _ = _session()
	assert "문항 2개" in session.respond("몇 문제 있어?").text


# --- 복습 노트 ------------------------------------------------------------------

def test_replies_are_recorded_to_the_review_log():
	log = ReviewLog()
	session, _, _ = _session(review_log=log)
	session.read_question(1)
	assert log.entries and "다음 표의 최고점은?" in log.entries[0].text
