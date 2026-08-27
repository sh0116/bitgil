#!/usr/bin/env python3
"""데모용 2026 모의고사(확장판) PDF 생성기 (개발 도구 — 런타임 의존성이 아닙니다).

`make_demo_exam.py`의 3문항 샘플보다 풍부한, 시연용 5문항 시험지를 만듭니다. 과외 모드가
실제로 하는 일을 한 부에 골고루 담는 것이 목적입니다.

    1번  개념형 객관식        — 도표 없음, 원문 직독
    2번  지문형 객관식        — 여러 줄 지문을 원문 그대로 읽는 장면
    3번  막대그래프(전부 라벨) — 도표 설명 + `factcheck`가 조용한(=근거 있는) 경우
    4번  막대그래프(라벨 하나 없음) — **보간 거부** 가드레일 (차트 해설 오류 1위)
    5번  개념형 객관식        — 도표 없음, 원문 직독

실제 기출은 저작권이 있어 쓸 수 없으므로 문항은 모두 자작입니다(사회탐구·경제 소재).
폰트·막대그래프 헬퍼는 `make_demo_exam.py`에서 그대로 가져와, 두 시험지가 같은 모양이
되도록 합니다.

    pip install reportlab
    python scripts/make_demo_exam_2026.py docs/demo/2026_모의고사_데모.pdf
"""

from __future__ import annotations

import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# 같은 폴더의 기존 생성기에서 폰트 등록·막대그래프 헬퍼를 재사용합니다(중복 방지).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_demo_exam import _FONT, _bar_chart, _register_font  # noqa: E402


def _choices(c, x, top, items):
	"""원문자 선택지 한 묶음을 줄줄이 그리고, 다음에 쓸 y 좌표를 돌려줍니다."""
	c.setFont(_FONT, 11)
	for i, choice in enumerate(items):
		c.drawString(x, top - i * 18, choice)
	return top - len(items) * 18


def _lines(c, x, top, rows, *, font=11, leading=16):
	"""여러 줄(지문 등)을 그리고 다음 y 좌표를 돌려줍니다."""
	c.setFont(_FONT, font)
	for i, row in enumerate(rows):
		c.drawString(x, top - i * leading, row)
	return top - len(rows) * leading


def build(path: str) -> None:
	_register_font()
	c = canvas.Canvas(path, pagesize=A4)
	width, height = A4

	# --- 1쪽: 머리글 + 1번(개념) + 2번(지문) -------------------------------
	c.setFont(_FONT, 14)
	c.drawString(60, height - 60, "2026학년도 대학수학능력시험 모의평가")
	c.setFont(_FONT, 10)
	c.drawString(60, height - 78, "사회탐구 영역 (경제) · 자작 예시 문항 (저작권 없는 데모용)")

	c.setFont(_FONT, 11)
	c.drawString(60, height - 120, "1. 다음 중 기회비용에 대한 설명으로 가장 적절한 것은?")
	_choices(c, 76, height - 145, [
		"① 어떤 선택을 위해 실제로 지출한 금액만을 뜻한다.",
		"② 포기한 대안들 가운데 가장 가치가 큰 것의 가치이다.",
		"③ 선택의 내용과 무관하게 항상 일정하게 유지된다.",
		"④ 이미 지출되어 회수할 수 없는 매몰비용과 같은 개념이다.",
		"⑤ 화폐로 환산할 수 없는 비용은 포함하지 않는다.",
	])

	c.setFont(_FONT, 11)
	c.drawString(60, height - 260, "2. 다음 글을 읽고 물음에 답하시오.")
	body_bottom = _lines(c, 76, height - 285, [
		"공공재는 여러 사람이 동시에 소비할 수 있으며, 대가를 지불하지 않은",
		"사람의 소비를 막기 어렵다. 이런 성질 때문에 사람들은 비용을 부담하지",
		"않고 이용하려는 유인을 갖는다. 그 결과 시장에 맡겨 두면 공공재는 사회가",
		"필요로 하는 양보다 적게 공급되는 경향이 있다.",
	])
	c.setFont(_FONT, 11)
	c.drawString(60, body_bottom - 12, "윗글에서 설명하는 현상으로 가장 적절한 것은?")
	_choices(c, 76, body_bottom - 34, [
		"① 규모의 경제",
		"② 무임승차 문제",
		"③ 독점적 경쟁",
		"④ 수요의 가격 탄력성",
		"⑤ 환율의 변동",
	])
	c.showPage()

	# --- 2쪽: 3번(전부 라벨 붙은 막대그래프) --------------------------------
	c.setFont(_FONT, 11)
	c.drawString(60, height - 80, "3. 다음 그래프는 어느 카페의 월별 방문자 수이다.")
	c.drawString(76, height - 98, "이에 대한 설명으로 옳은 것은?")
	# 라벨은 원문자 없이 도표 안 글자로 분리되도록 '월' 단위를 씁니다(1월·2월…은
	# figure_text로 깨끗이 빠지지만, '월·화'처럼 숫자로 시작하지 않는 라벨은 지문에
	# 섞여 낭독이 지저분해집니다 — document.py의 _FIGURE_TOKEN 참고).
	_bar_chart(c, 110, height - 300, 380, 160,
	           [("1월", 80), ("2월", 60), ("3월", 100), ("4월", 140)])
	_choices(c, 76, height - 350, [
		"① 방문자 수는 매월 늘어났다.",
		"② 방문자가 가장 많은 달은 4월이다.",
		"③ 3월 방문자는 1월보다 적다.",
		"④ 2월 방문자가 가장 많다.",
		"⑤ 1월과 2월의 방문자 수는 같다.",
	])
	c.showPage()

	# --- 3쪽: 4번(라벨 하나 없는 막대 = 가드레일) + 5번(개념) ---------------
	c.setFont(_FONT, 11)
	c.drawString(60, height - 80, "4. 다음 그래프는 어느 도서관의 연도별 대출 건수이다.")
	c.drawString(76, height - 98, "2023년의 대출 건수에 대한 설명으로 옳은 것은?")
	_bar_chart(c, 110, height - 300, 380, 160,
	           [("2021년", 300), ("2022년", 450), ("2023년", 520), ("2024년", 600)],
	           hide_label_at=2)
	# 축 라벨(막대 아래 y-13)과 겹치지 않도록 한 줄 더 아래에 각주를 둡니다.
	c.setFont(_FONT, 9)
	c.drawString(76, height - 340, "※ 2023년 막대의 값은 그래프에 표시되어 있지 않다.")
	_choices(c, 76, height - 366, [
		"① 2022년보다 적다.",
		"② 2024년보다 많다.",
		"③ 그래프만으로는 정확한 값을 알 수 없다.",
		"④ 정확히 500건이다.",
		"⑤ 2021년의 세 배이다.",
	])

	c.setFont(_FONT, 11)
	c.drawString(60, height - 520, "5. 다음 중 수요의 법칙에 대한 설명으로 옳은 것은?")
	_choices(c, 76, height - 545, [
		"① 가격이 오르면 수요량이 늘어난다.",
		"② 다른 조건이 같을 때 가격이 오르면 수요량이 줄어든다.",
		"③ 소득이 늘어도 수요는 변하지 않는다.",
		"④ 수요량은 가격과 무관하게 결정된다.",
		"⑤ 대체재의 가격은 수요에 영향을 주지 않는다.",
	])
	c.save()
	print(f"{path} 생성 완료")


if __name__ == "__main__":
	out = sys.argv[1] if len(sys.argv) > 1 else "docs/demo/2026_모의고사_데모.pdf"
	os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
	build(out)
