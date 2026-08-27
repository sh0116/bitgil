#!/usr/bin/env python3
"""데모용 모의고사 PDF 생성기 (개발 도구 — 런타임 의존성이 아닙니다).

실제 모의고사·수능 기출은 저작권이 있어 시연 영상에 쓸 수 없습니다. 그래서 같은 형식의
문항을 직접 만들어 씁니다. 형식은 국내 시험지 관례를 따릅니다 — 줄 앞의 문항 번호,
원문자 선택지(①~⑤), 문항에 딸린 도표.

3번 문항은 **의도적으로 막대 하나에 값 라벨을 넣지 않았습니다.** 눈금에서 값을 보간해
말하는 것이 차트 해설 오류 1위이고([docs/evidence.md]), 우리 가드레일(프로파일 규칙 +
`factcheck`)이 실제로 작동하는지 보려면 유혹이 있는 자료가 필요합니다.

    pip install reportlab   # 이 스크립트만 필요
    python scripts/make_demo_exam.py docs/demo/모의고사_샘플.pdf
"""

from __future__ import annotations

import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_FONT_CANDIDATES = (
	"/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
	"/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
	"/System/Library/Fonts/AppleSDGothicNeo.ttc",
	"C:/Windows/Fonts/malgun.ttf",
)
_FONT = "KR"


def _register_font() -> None:
	for path in _FONT_CANDIDATES:
		if os.path.exists(path):
			pdfmetrics.registerFont(TTFont(_FONT, path))
			return
	sys.exit(
		"한글 폰트를 찾지 못했습니다. NanumGothic을 설치하거나 "
		"_FONT_CANDIDATES에 폰트 경로를 추가하세요."
	)


def _bar_chart(c, x, y, w, h, bars, hide_label_at=None):
	"""막대 그래프. `hide_label_at` 인덱스의 막대는 값 라벨을 그리지 않습니다."""
	top = max(v for _, v in bars)
	c.setLineWidth(1)
	c.line(x, y, x + w, y)           # x축
	c.line(x, y, x, y + h)           # y축
	slot = w / len(bars)
	for i, (label, value) in enumerate(bars):
		bar_h = (value / top) * (h - 30)
		bx = x + i * slot + slot * 0.25
		c.setFillColorRGB(0.23, 0.44, 0.83)
		c.rect(bx, y, slot * 0.5, bar_h, stroke=0, fill=1)
		c.setFillColorRGB(0, 0, 0)
		c.setFont(_FONT, 9)
		c.drawCentredString(bx + slot * 0.25, y - 13, label)
		if i != hide_label_at:
			c.drawCentredString(bx + slot * 0.25, y + bar_h + 4, str(value))
	# y축 눈금 — 라벨 없는 막대의 값을 "보간하고 싶게" 만드는 부분.
	c.setFont(_FONT, 8)
	for step in range(0, 5):
		v = round(top * step / 4)
		gy = y + (v / top) * (h - 30)
		c.line(x - 4, gy, x, gy)
		c.drawRightString(x - 7, gy - 3, str(v))


def build(path: str) -> None:
	_register_font()
	c = canvas.Canvas(path, pagesize=A4)
	width, height = A4

	# --- 1쪽 ---------------------------------------------------------------
	c.setFont(_FONT, 14)
	c.drawString(60, height - 60, "2026학년도 대학수학능력시험 모의평가 (예시 문항)")
	c.setFont(_FONT, 10)
	c.drawString(60, height - 78, "사회탐구 영역 · 자작 예시 문항 (저작권 없는 데모용)")

	c.setFont(_FONT, 11)
	c.drawString(60, height - 120, "1. 다음 중 표본조사의 특징으로 옳은 것은?")
	for i, choice in enumerate([
		"① 모집단 전체를 조사한다.",
		"② 조사 비용이 전수조사보다 적게 든다.",
		"③ 표본의 크기는 결과에 영향을 주지 않는다.",
		"④ 항상 전수조사보다 정확하다.",
		"⑤ 표본을 임의로 고르면 대표성이 높아진다.",
	]):
		c.drawString(76, height - 145 - i * 18, choice)

	c.drawString(60, height - 265, "2. 다음 그래프는 어느 가게의 월별 판매량을 나타낸 것이다.")
	c.drawString(76, height - 283, "이에 대한 설명으로 옳은 것은?")
	_bar_chart(c, 110, height - 460, 380, 150,
	           [("1월", 120), ("2월", 200), ("3월", 90), ("4월", 260)])
	for i, choice in enumerate([
		"① 판매량은 매월 증가하였다.",
		"② 3월의 판매량이 가장 많다.",
		"③ 4월의 판매량은 1월의 두 배가 넘는다.",
		"④ 2월과 3월의 판매량은 같다.",
		"⑤ 판매량이 가장 적은 달은 1월이다.",
	]):
		c.drawString(76, height - 500 - i * 18, choice)
	c.showPage()

	# --- 2쪽: 라벨 없는 막대(가드레일 시연용) --------------------------------
	c.setFont(_FONT, 11)
	c.drawString(60, height - 80, "3. 다음 그래프는 어느 지역의 연도별 이용자 수이다.")
	c.drawString(76, height - 98, "2023년의 이용자 수에 대한 설명으로 옳은 것은?")
	_bar_chart(c, 110, height - 300, 380, 160,
	           [("2021년", 300), ("2022년", 450), ("2023년", 520), ("2024년", 600)],
	           hide_label_at=2)
	c.setFont(_FONT, 9)
	c.drawString(110, height - 320, "※ 2023년 막대의 값은 그래프에 표시되어 있지 않다.")
	c.setFont(_FONT, 11)
	for i, choice in enumerate([
		"① 2022년보다 적다.",
		"② 2024년보다 많다.",
		"③ 2021년의 두 배이다.",
		"④ 그래프만으로는 정확한 값을 알 수 없다.",
		"⑤ 500명이다.",
	]):
		c.drawString(76, height - 350 - i * 18, choice)
	c.save()
	print(f"{path} 생성 완료")


if __name__ == "__main__":
	out = sys.argv[1] if len(sys.argv) > 1 else "docs/demo/모의고사_샘플.pdf"
	os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
	build(out)
