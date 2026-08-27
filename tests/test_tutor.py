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


def _session(reply="막대 네 개가 있습니다.", review_log=None, title=""):
	doc = FakeDocument(
		path=type("P", (), {"name": "모의고사.pdf"})(),
		pages=["1. 다음 표는 월별 판매량이다. 1월 120, 4월 260"],
		questions=[
			Question(number=1, stem="다음 표의 최고점은?", choices=["1월", "4월"], page=0),
			Question(number=2, stem="증가 추세인가?", choices=[], page=0),
		],
		title=title,
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


def test_repeat_keeps_the_reply_marked_as_the_model_speaking():
	# "다시"가 모델의 답을 원문으로 바꿔 읽으면, 이 모드가 약속한 단 하나의 구분이 깨진다 —
	# 듣는 사람은 시험지에 인쇄된 문장과 모델이 한 말을 목소리로 구별할 수 없다.
	session, _, _ = _session(reply="이 문제는 그래프 해석을 묻습니다.")
	session.read_question(1)
	answered = session.ask("이 문제는 뭘 묻는 거야")
	assert answered.grounded is False
	again = session.repeat()
	assert again.text == answered.text
	assert again.grounded is False
	assert again.unsupported == answered.unsupported


def test_repeat_does_not_record_the_reply_twice():
	# 같은 문장을 두 번 들은 것이 복습 노트에서 두 번 일어난 일은 아니다.
	review = ReviewLog(clock=lambda: "10:00")
	session, _, _ = _session(review_log=review)
	session.read_question(1)
	session.repeat()
	assert review.to_markdown().count("1번.") == 1


def test_repeat_before_anything_gives_the_overview():
	session, _, _ = _session()
	assert "문항 2개" in session.repeat().text


def test_overview_counts_questions_and_pages():
	session, _, _ = _session()
	text = session.overview().text
	assert "문항 2개" in text and "1번부터 2번까지" in text


def test_the_word_overview_re_reads_the_overview():
	# tutor.html의 "개요 다시" 버튼이 보내는 말. 개요 없이 떨어지면 학생은 자리를 잃는다.
	session, provider, _ = _session()
	reply = session.respond("개요")
	assert "문항 2개" in reply.text
	assert provider.calls == 0  # 개요는 왕복 없이, 근거만으로.


# --- 시험지를 펼쳤을 때: 무슨 시험지인지 말하고 기다린다 ----------------------------

def test_overview_reads_the_printed_header_not_the_file_name():
	# 파일명은 귀로 듣는 학생에게 정보가 아니다 — 시험지에 인쇄된 머리글이 정보다.
	session, _, _ = _session(title="2026학년도 모의평가\n사회탐구 영역")
	text = session.overview().text
	assert text.startswith("2026학년도 모의평가\n사회탐구 영역")
	assert "모의고사.pdf" not in text


def test_overview_never_calls_the_model():
	# 시험지를 펼치는 것만으로 왕복 비용이나 환각 위험이 생기면 안 된다.
	session, provider, _ = _session(title="2026학년도 모의평가")
	reply = session.overview()
	assert provider.calls == 0
	assert reply.grounded is True


def test_overview_says_which_questions_have_a_figure():
	session, _, doc = _session()
	doc.questions[1].figure_text = "1월 120 4월 260"
	assert "도표나 그림이 딸린 문항은 2번입니다" in session.overview().text


def test_overview_says_which_questions_have_no_choices_it_could_read():
	session, _, _ = _session()
	assert "선택지를 읽지 못한 문항은 2번입니다" in session.overview().text


def test_overview_ends_by_handing_the_turn_back_to_the_student():
	# 설명하고 **기다린다** — 무엇을 먼저 들을지는 학생이 정한다.
	assert _session()[0].overview().text.rstrip().endswith("문항 번호만 말해도 됩니다.")


def test_overview_caps_a_long_figure_list_and_says_how_many():
	# 스무 개를 줄줄이 읽는 것은 안내가 아니라 소음이다.
	session, _, doc = _session()
	doc.questions = [
		Question(number=n, stem=f"{n}번 지문", choices=["가"], page=0, figure_text="1 2 3 4")
		for n in range(1, 21)
	]
	text = session.overview().text
	assert "등 모두 20개입니다" in text
	assert "9번" not in text          # 상한을 넘긴 번호는 읽지 않는다


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


# --- 이끌어 주는 과외 흐름: 진행 표시 · 다음 행동 안내 · 코칭 -----------------------

def test_reading_a_question_says_where_we_are():
	# 귀로만 듣는 학생에게 "지금 몇 번째"는 페이지를 못 보면 알 수 없는 정보다.
	session, provider, _ = _session()
	reply = session.read_question(1)
	assert "2문항 중 1번째입니다." in reply.text
	assert provider.calls == 0          # 진행 표시는 세는 것 — 모델을 거치지 않는다
	assert reply.grounded is True


def test_reading_a_question_offers_only_the_actions_that_apply():
	# 1번은 선택지가 있고 뒤에 문항이 더 있다 → 선택지·다음이 안내된다. 그림은 없다.
	session, _, _ = _session()
	menu = session.read_question(1).text
	assert "선택지 다시 듣기" in menu
	assert "다음 문제로 가기" in menu
	assert "도표 설명" not in menu       # 1번엔 그림이 없다 — 거짓 안내를 하지 않는다


def test_last_question_does_not_offer_a_next():
	session, _, _ = _session()
	menu = session.read_question(2).text        # 2번이 마지막
	assert "다음 문제로 가기" not in menu
	assert "선택지 다시 듣기" not in menu       # 2번은 서술형(선택지 없음)


def test_menu_offers_the_figure_action_only_when_there_is_a_figure():
	session, _, doc = _session()
	doc.questions[0].figure_text = "1월 120 4월 260"
	assert "도표 설명 듣기" in session.read_question(1).text


def test_start_word_enters_the_first_question():
	# 개요를 듣고 "시작"이라고 하면 첫 문제로 들어간다("1번부터 같이 볼까요?"에 대한 승낙).
	session, provider, _ = _session()
	reply = session.respond("시작")
	assert "1번." in reply.text
	assert provider.calls == 0


def test_asking_for_the_answer_coaches_instead_of_answering():
	# 정답을 대신 부르지 않는다 — 모델로 넘기지도 않고 접근법으로 되돌린다.
	session, provider, _ = _session()
	session.read_question(1)
	reply = session.respond("정답이 뭐야?")
	assert provider.calls == 0
	assert reply.grounded is True
	assert "직접 고를 때" in reply.text
	assert "선택지" in reply.text          # 1번엔 선택지가 있으니 그 길로 안내


def test_answer_seeking_with_a_number_sets_that_question_first():
	# "2번이 답이야?"는 2번을 지목한 뒤 코칭 — 지목은 반영되어야 한다.
	session, _, _ = _session()
	session.read_question(1)
	reply = session.respond("2번이 답이야?")
	assert session.current.number == 2
	# 2번은 서술형이라 선택지 대신 '무엇을 묻는지'로 안내한다.
	assert "이 문제가 뭘 묻는지" in reply.text


def test_a_plain_what_does_it_ask_still_reaches_the_model():
	# 코칭이 정상적인 설명 요청까지 가로채면 안 된다 — "답해줘"는 '답' 어구가 아니다.
	session, provider, _ = _session(reply="이 문제는 최고점을 묻습니다.")
	session.read_question(1)
	session.respond("이 문제 뭘 묻는지 답해줘")
	assert provider.calls == 1


def test_free_form_answers_go_through_the_glossary():
	# 물어보기 경로도 화면 해설과 같은 후처리를 거친다 — 용어집이 양쪽에서 똑같이 적용된다.
	doc = FakeDocument(
		path=type("P", (), {"name": "x.pdf"})(),
		pages=["1. 캐릭터 상태를 보라."],
		questions=[Question(number=1, stem="HP는?", choices=["높다"], page=0)],
	)
	provider = FakeProvider(reply="HP가 낮습니다.")
	profile = Profile(name="t", system_prompt="s", glossary={"HP": "체력"})
	session = TutorSession(doc, NarrationEngine(provider, profile))
	session.read_question(1)
	assert "체력" in session.ask("이 문제 뭘 묻는 거야?").text


# --- 복습 노트 ------------------------------------------------------------------

def test_replies_are_recorded_to_the_review_log():
	log = ReviewLog()
	session, _, _ = _session(review_log=log)
	session.read_question(1)
	assert log.entries and "다음 표의 최고점은?" in log.entries[0].text
