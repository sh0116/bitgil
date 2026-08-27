"""문서 직독 — 시험지 PDF의 텍스트 레이어를 근거(ground truth)로 쓰는 입력 계층.

화면 캡처 경로는 지문·선택지·인쇄된 수치까지 전부 비전 LLM을 통과합니다. 즉 모델이
"읽었다고 주장하는" 값이고, 시각장애 학생에게는 그것을 검증할 방법이 없습니다
([docs/evidence.md]: BLV 사용자는 AI 오류를 약 50%만 잡아냅니다). 시험지 PDF에는 대개
텍스트 레이어가 있고, 거기서 뽑은 문자열은 추측이 아니라 **원문**입니다. 그래서 지문과
선택지는 LLM을 거치지 않고 이 모듈이 직접 읽고, 비전은 도표·그림에만 씁니다 — 앰비언트
코파일럿 설계의 "구조화 데이터 우선, 비전은 선택적 보조"와 같은 계층 구조입니다.

페이지 래스터화는 poppler의 `pdftoppm`을 **별도 실행 파일로 호출**합니다. PyMuPDF가 텍스트와
렌더링을 한 번에 해주지만 AGPL이라 MIT 코어에 넣을 수 없습니다. pypdf(BSD-3)는 순수
파이썬이어서 애드온 벤더링 제약(순수 파이썬만)과도 맞습니다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# 원문자 선택지(①~⑩)는 국내 시험지의 사실상 표준 표기입니다.
_CHOICE_MARKS = "①②③④⑤⑥⑦⑧⑨⑩"
_CHOICE_SPLIT = re.compile(f"(?=[{_CHOICE_MARKS}])")

# "3." / "3)" / "문 3." — 줄 맨 앞의 문항 번호. 지시문·날짜("2026. 8.")가 섞여 들어오므로
# 번호만으로는 못 믿고, 아래 `split_questions`가 **번호 연속성**으로 한 번 더 걸러냅니다.
_QUESTION_START = re.compile(r"^\s*(?:문\s*)?(\d{1,2})\s*[.)]\s*(.*)$")

# 텍스트 레이어가 이보다 적으면 스캔 이미지 PDF로 봅니다(문자가 그림 안에 있는 경우).
_SCANNED_THRESHOLD = 40


@dataclass
class Question:
	"""한 문항. `stem`·`choices`는 모델을 거치지 않은 PDF 원문입니다.

	`figure_text`는 도표 안에 인쇄된 글자(축 눈금, 막대 라벨)입니다. 지문과 **분리해서**
	들고 있는 이유는 낭독과 근거의 쓰임이 다르기 때문입니다: 눈금 값을 문장 중간에 그대로
	읽으면("…옳은 것은? 0 65 130 195") 귀로 듣는 사람에게는 소음이지만, 모델이 말한 숫자가
	화면에 인쇄된 것인지 대조할 때는 반드시 있어야 하는 근거입니다.
	"""

	number: int
	stem: str
	choices: List[str] = field(default_factory=list)
	page: int = 0
	figure_text: str = ""

	def spoken(self) -> str:
		"""낭독용 한 덩어리 — 지문, 도표 안내, 그다음 선택지를 번호와 함께."""
		parts = [f"{self.number}번. {self.stem}".strip()]
		if self.figure_text:
			parts.append("이 문항에는 도표가 있습니다. '도표 설명해줘'라고 말해 주세요.")
		for i, choice in enumerate(self.choices, start=1):
			parts.append(f"{i}번 선택지, {choice}")
		return "\n".join(parts)

	def source_text(self) -> str:
		"""사실 대조(factcheck)의 근거로 쓰는 이 문항의 원문 전체(도표 글자 포함)."""
		return "\n".join([self.stem, self.figure_text, *self.choices])


@dataclass
class ExamDocument:
	"""읽어들인 시험지 한 부."""

	path: Path
	pages: List[str]
	questions: List[Question]

	def question(self, number: int) -> Optional[Question]:
		for q in self.questions:
			if q.number == number:
				return q
		return None

	def page_text(self, index: int) -> str:
		return self.pages[index] if 0 <= index < len(self.pages) else ""

	def render_page(self, index: int, dpi: int = 150) -> bytes:
		return render_page(self.path, index, dpi=dpi)


def load_pdf(path: str | Path) -> ExamDocument:
	"""PDF의 텍스트 레이어를 읽어 문항으로 나눕니다.

	스캔 이미지 PDF는 여기서 **막습니다**. 텍스트 레이어가 없으면 이 계층이 보장하는
	정확도가 성립하지 않는데, 조용히 비전 경로로 흘리면 사용자는 근거 있는 낭독과
	모델 추측을 구분할 수 없게 됩니다. 그래서 무엇이 문제이고 무엇을 하면 되는지
	한국어 한 문장으로 알려주고 멈춥니다.
	"""
	path = Path(path)
	if not path.exists():
		raise FileNotFoundError(f"문서를 찾을 수 없습니다: {path}")
	try:
		from pypdf import PdfReader
	except ImportError:  # pragma: no cover - 설치 안내용
		raise RuntimeError(
			"PDF를 읽으려면 pypdf가 필요합니다. `pip install pypdf`로 설치하세요."
		) from None

	reader = PdfReader(str(path))
	pages = [(p.extract_text() or "") for p in reader.pages]
	if sum(len(t.strip()) for t in pages) < _SCANNED_THRESHOLD:
		raise ValueError(
			f"{path.name}은 글자가 그림으로만 들어 있어(스캔 PDF) 원문을 그대로 읽을 수 "
			"없습니다. 글자가 살아 있는 PDF를 쓰거나, 화면 공유 모드로 읽어 주세요."
		)
	questions: List[Question] = []
	for index, text in enumerate(pages):
		questions.extend(split_questions(text, page=index))
	return ExamDocument(path=path, pages=pages, questions=questions)


def split_questions(text: str, page: int = 0) -> List[Question]:
	"""페이지 텍스트를 문항 단위로 나눕니다.

	번호처럼 보이는 것(날짜 "2026. 8.", 각주, 표 안의 숫자)이 흔해서 정규식만으로는
	문항이 폭발합니다. 그래서 **번호가 이어질 때만** 새 문항을 엽니다 — 첫 문항이거나
	직전 문항 번호 + 1일 때. 시험지는 번호가 순서대로 붙는다는 성질을 쓰는 것이고,
	덕분에 오탐이 문항 목록을 오염시키지 않습니다. 대신 페이지가 3번부터 시작하는
	발췌본에서는 첫 번호를 그대로 받아들입니다(연속성은 그 다음부터 확인).
	"""
	found: List[Question] = []
	buffer: List[str] = []
	expected: Optional[int] = None

	def flush() -> None:
		if not found or not buffer:
			return
		stem, choices = _split_choices("\n".join(buffer))
		prose, figure = _split_figure_text(_tidy(f"{found[-1].stem} {stem}"))
		found[-1].stem = prose
		found[-1].figure_text = figure
		found[-1].choices = choices

	for line in text.splitlines():
		match = _QUESTION_START.match(line)
		number = int(match.group(1)) if match else None
		if number is not None and (expected is None or number == expected):
			flush()
			buffer = []
			found.append(Question(number=number, stem=_tidy(match.group(2)), page=page))
			expected = number + 1
			continue
		if found:
			buffer.append(line)
	flush()
	return found


def _split_choices(blob: str) -> tuple[str, List[str]]:
	"""문항 본문을 (지문, 선택지 목록)으로 자릅니다. 원문자 표기가 없으면 선택지는 빈 목록."""
	parts = [p for p in _CHOICE_SPLIT.split(blob) if p.strip()]
	if not parts:
		return "", []
	stem = parts[0] if parts[0][:1] not in _CHOICE_MARKS else ""
	rest = parts if not stem else parts[1:]
	choices = [_tidy(p.lstrip(_CHOICE_MARKS)) for p in rest if p.strip()[:1] in _CHOICE_MARKS]
	return _tidy(stem), choices


def _tidy(text: str) -> str:
	"""PDF 추출물의 줄바꿈·중복 공백을 낭독 가능한 한 줄로 정리."""
	return " ".join(text.split())


# 도표 안의 글자로 볼 토큰: 맨숫자(120, 1,200, 3.5)이거나 숫자+단위(1월, 2021년, 30%).
_FIGURE_TOKEN = re.compile(r"^\d+(?:,\d{3})*(?:\.\d+)?(?:월|년|일|시|분|회|차|위|점|명|개|%)?$")

# 도표로 인정할 최소 토큰 수. 지문 안의 낱개 숫자("두 배", "3의 배수")를 도표로 오인해
# 지문에서 빼내면 뜻이 무너지므로, 라벨이 줄지어 나올 때만 도표로 봅니다.
_FIGURE_RUN_MIN = 4


def _split_figure_text(stem: str) -> tuple[str, str]:
	"""지문에서 도표 안 글자 덩어리를 분리해 (지문, 도표 글자)로 반환.

	PDF 텍스트 레이어는 도표의 축 눈금·막대 라벨을 지문과 같은 흐름에 섞어 내놓습니다
	(좌표를 버리기 때문입니다). 문장 부호로 자르는 방법은 도표 **뒤에** 각주가 오는 문항에서
	깨지므로, 대신 **숫자·라벨 토큰이 줄지어 나오는 구간**을 찾아 빼냅니다. 레이아웃 좌표를
	쓰면 더 정확하지만, 그건 pypdf 방문자 API가 필요한 후속 작업입니다.
	"""
	tokens = stem.split()
	keep: List[str] = []
	figure: List[str] = []
	index = 0
	while index < len(tokens):
		run = index
		while run < len(tokens) and _FIGURE_TOKEN.match(tokens[run]):
			run += 1
		length = run - index
		if length >= _FIGURE_RUN_MIN:
			figure.extend(tokens[index:run])
			index = run
			continue
		keep.extend(tokens[index:run] or [tokens[index]])
		index = run + 1 if length == 0 else run
	return " ".join(keep), " ".join(figure)


def render_page(path: str | Path, index: int, dpi: int = 150) -> bytes:
	"""페이지 한 장을 PNG로 렌더링합니다(도표 설명용 비전 입력).

	pdftoppm은 표준출력(`-`)으로 내보내는 동작이 배포판마다 달라서(이 파이의 22.12에서는
	0바이트) 임시 파일을 거칩니다. 캡처 프레임과 마찬가지로 디스크에 남기지 않습니다.
	"""
	path = Path(path)
	binary = shutil.which("pdftoppm")
	if binary is None:
		raise RuntimeError(
			"페이지 그림을 만들려면 pdftoppm이 필요합니다. "
			"`sudo apt install poppler-utils`(맥은 `brew install poppler`)로 설치하세요."
		)
	page_number = index + 1
	with tempfile.TemporaryDirectory() as tmp:
		root = Path(tmp) / "page"
		result = subprocess.run(
			[
				binary, "-png", "-r", str(dpi),
				"-f", str(page_number), "-l", str(page_number),
				"-singlefile", str(path), str(root),
			],
			capture_output=True,
		)
		out = root.with_suffix(".png")
		if result.returncode != 0 or not out.exists():
			reason = (result.stderr or b"").decode("utf-8", "replace").strip()
			raise RuntimeError(
				f"{path.name} {page_number}쪽을 그림으로 만들지 못했습니다"
				f"{': ' + reason if reason else ''}."
			)
		return out.read_bytes()
