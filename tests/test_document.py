"""Tests for 문서 직독 — PDF 텍스트 레이어 추출, 문항 분할, 페이지 렌더링.

All offline. The PDF fixture is built by hand (a real text layer with correct xref
offsets) rather than with a generator dependency, and the scanned-PDF path uses a
Pillow-rendered PDF — which genuinely has no text layer, so it exercises the real
rejection rather than a mocked one.
"""

import io
import shutil

import pytest
from PIL import Image

from bitgil_core.document import (
	ExamDocument,
	Question,
	load_pdf,
	render_page,
	split_questions,
)

pytest.importorskip("pypdf")


def _pdf_with_text(lines) -> bytes:
	"""Minimal single-page PDF carrying a real text layer."""
	drawn = "".join(f"({line}) Tj T*\n" for line in lines)
	content = "BT /F1 12 Tf 72 720 Td 14 TL\n" + drawn + "ET"
	objs = [
		"<</Type/Catalog/Pages 2 0 R>>",
		"<</Type/Pages/Kids[3 0 R]/Count 1>>",
		"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
		"/Resources<</Font<</F1 5 0 R>>>>>>",
		f"<</Length {len(content)}>>\nstream\n{content}\nendstream",
		"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
	]
	out = "%PDF-1.4\n"
	offsets = []
	for i, body in enumerate(objs, start=1):
		offsets.append(len(out))
		out += f"{i} 0 obj\n{body}\nendobj\n"
	xref = len(out)
	out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
	out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
	out += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n"
	return out.encode("latin-1")


def _scanned_pdf() -> bytes:
	"""A PDF whose glyphs are pixels — i.e. no text layer at all."""
	buf = io.BytesIO()
	Image.new("RGB", (300, 400), "white").save(buf, format="PDF")
	return buf.getvalue()


# --- 문항 분할 ----------------------------------------------------------------

def test_split_questions_reads_stem_and_circled_choices():
	text = "3. 다음 그래프의 최고점은?\n① 1월 ② 2월 ③ 3월 ④ 4월"
	[q] = split_questions(text)
	assert q.number == 3
	assert q.stem == "다음 그래프의 최고점은?"
	assert q.choices == ["1월", "2월", "3월", "4월"]


def test_split_questions_requires_consecutive_numbers():
	# 지시문 안의 날짜("2026. 8.")와 각주 번호가 문항으로 오인되면 목록이 폭발한다.
	# 번호 연속성을 요구하면 1 → 2만 문항으로 열린다.
	text = "1. 첫 문제\n출처: 2026. 8. 자료\n2. 둘째 문제\n99. 각주처럼 보이는 줄"
	numbers = [q.number for q in split_questions(text)]
	assert numbers == [1, 2]


def test_split_questions_accepts_an_excerpt_starting_midway():
	# 발췌본은 3번부터 시작할 수 있다 — 첫 번호는 그대로 받고, 연속성은 그 다음부터.
	numbers = [q.number for q in split_questions("3. 셋째\n4. 넷째")]
	assert numbers == [3, 4]


def test_split_questions_joins_wrapped_stem_lines():
	text = "1. 다음 표는 월별\n판매량을 나타낸다.\n① 가 ② 나"
	[q] = split_questions(text)
	assert q.stem == "다음 표는 월별 판매량을 나타낸다."


def test_split_questions_without_choices_leaves_them_empty():
	[q] = split_questions("1. 서술형 문항입니다. 이유를 쓰시오.")
	assert q.choices == []
	assert "이유를 쓰시오." in q.stem


def test_split_questions_separates_chart_labels_from_the_stem():
	# PDF 텍스트 레이어는 축 눈금을 지문 흐름에 섞어 내놓는다. 그대로 읽으면 귀로 듣는
	# 사람에게 "…옳은 것은? 0 65 130 195"가 되어 소음이 된다.
	text = (
		"2. 다음 그래프는 월별 판매량이다. 옳은 것은?\n"
		"1월 120 2월 200 3월 90 4월 260 0 65 130 195\n① 가 ② 나"
	)
	[q] = split_questions(text)
	assert q.stem == "다음 그래프는 월별 판매량이다. 옳은 것은?"
	assert "120" in q.figure_text and "195" in q.figure_text
	assert "120" not in q.stem


def test_figure_text_stays_in_source_text_as_evidence():
	# 낭독에서는 빼지만 근거에서는 빼지 않는다 — 대조할 값이 사라지면 factcheck가 오탐한다.
	text = "2. 옳은 것은?\n1월 120 2월 200 3월 90 4월 260\n① 가"
	[q] = split_questions(text)
	assert "120" in q.source_text()
	assert "120" not in q.spoken()
	assert "도표가 있습니다" in q.spoken()   # 도표가 있다는 사실은 알려줘야 한다


def test_a_lone_number_in_prose_is_not_treated_as_a_chart():
	# "두 배", "3의 배수"처럼 지문 안의 낱개 숫자를 빼내면 문장의 뜻이 무너진다.
	[q] = split_questions("1. 4월의 값은 1월의 2배인가?\n① 예")
	assert q.figure_text == ""
	assert "2배인가?" in q.stem


def test_a_footnote_after_the_chart_stays_in_the_stem():
	# 도표 뒤에 각주가 오는 문항 — 문장 부호로 자르는 방식이 깨지는 자리다.
	text = (
		"3. 2023년의 값에 대한 설명으로 옳은 것은?\n"
		"2021년 300 2022년 450 2023년 2024년 600\n"
		"※ 2023년 막대의 값은 표시되어 있지 않다.\n① 가"
	)
	[q] = split_questions(text)
	assert "표시되어 있지 않다." in q.stem
	assert "450" in q.figure_text


def test_split_questions_records_page_index():
	[q] = split_questions("1. 문제", page=4)
	assert q.page == 4


def test_split_questions_empty_text_is_empty_list():
	assert split_questions("") == []


# --- 낭독 문자열 --------------------------------------------------------------

def test_question_spoken_numbers_the_choices():
	q = Question(number=2, stem="무엇인가?", choices=["가", "나"])
	spoken = q.spoken()
	assert spoken.startswith("2번. 무엇인가?")
	assert "1번 선택지, 가" in spoken and "2번 선택지, 나" in spoken


def test_question_source_text_includes_choices():
	q = Question(number=1, stem="값은 120인가?", choices=["200", "90"])
	source = q.source_text()
	assert "120" in source and "200" in source and "90" in source


# --- load_pdf ------------------------------------------------------------------

def test_load_pdf_extracts_text_layer_and_questions(tmp_path):
	path = tmp_path / "exam.pdf"
	path.write_bytes(_pdf_with_text(["1. Read the chart below.", "2. What is shown?"]))
	doc = load_pdf(path)
	assert len(doc.pages) == 1
	assert [q.number for q in doc.questions] == [1, 2]
	assert doc.question(1).stem == "Read the chart below."
	assert doc.question(9) is None


def test_load_pdf_rejects_a_scanned_pdf_with_actionable_korean(tmp_path):
	# 스캔 PDF를 조용히 비전 경로로 흘리면 근거 있는 낭독과 모델 추측을 구분할 수 없다.
	path = tmp_path / "scan.pdf"
	path.write_bytes(_scanned_pdf())
	with pytest.raises(ValueError) as err:
		load_pdf(path)
	assert "스캔 PDF" in str(err.value)
	assert "화면 공유" in str(err.value)   # 무엇을 하면 되는지가 문장 안에 있어야 한다


def test_load_pdf_missing_file_names_the_path(tmp_path):
	with pytest.raises(FileNotFoundError):
		load_pdf(tmp_path / "없는파일.pdf")


def test_page_text_out_of_range_is_empty(tmp_path):
	doc = ExamDocument(path=tmp_path / "x.pdf", pages=["첫 쪽"], questions=[])
	assert doc.page_text(0) == "첫 쪽"
	assert doc.page_text(5) == ""
	assert doc.page_text(-1) == ""


# --- render_page ---------------------------------------------------------------

def test_render_page_without_pdftoppm_says_how_to_install(tmp_path, monkeypatch):
	monkeypatch.setattr("bitgil_core.document.shutil.which", lambda _: None)
	with pytest.raises(RuntimeError) as err:
		render_page(tmp_path / "x.pdf", 0)
	assert "poppler-utils" in str(err.value)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler-utils 미설치")
def test_render_page_returns_png_bytes(tmp_path):
	path = tmp_path / "exam.pdf"
	path.write_bytes(_pdf_with_text(["1. Hello"]))
	png = render_page(path, 0, dpi=50)
	assert png[:8] == b"\x89PNG\r\n\x1a\n"
	assert Image.open(io.BytesIO(png)).size[0] > 0


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler-utils 미설치")
def test_render_page_out_of_range_reports_the_page(tmp_path):
	path = tmp_path / "exam.pdf"
	path.write_bytes(_pdf_with_text(["1. Hello"]))
	with pytest.raises(RuntimeError) as err:
		render_page(path, 8)
	assert "9쪽" in str(err.value)
