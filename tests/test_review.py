"""Tests for F4 review notes and profile observe_interval (offline)."""

import io

from PIL import Image

from bitgil_core.engine import NarrationEngine
from bitgil_core.profiles import Profile
from bitgil_core.providers.base import VisionProvider, VisionResponse
from bitgil_core.review import ReviewLog


class FixedProvider(VisionProvider):
	name = "fixed"

	def __init__(self, reply):
		self.reply = reply

	def complete(self, messages, *, max_tokens=300):
		return VisionResponse(text=self.reply)

	def stream(self, messages, *, max_tokens=300):
		yield self.reply


def _png() -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", (16, 16), "red").save(buf, format="PNG")
	return buf.getvalue()


def test_review_log_markdown_with_timestamps():
	log = ReviewLog(title="세션", clock=lambda: "00:01")
	log.record("첫 해설")
	log.record("  둘째 해설  ")   # trimmed
	log.record("")                # empty ignored
	md = log.to_markdown()
	# Machine-generated disclaimer + generated-at lead the document, then entries.
	assert md == (
		"# 세션\n\n"
		"> ⚠️ 이 노트는 AI가 화면을 보고 자동 생성한 것으로, 사실과 다른 내용이 있을 수 "
		"있습니다. 학습에 사용하기 전 반드시 사람이 원본과 대조해 검토하세요.\n"
		">\n"
		"> 생성: 00:01\n\n"
		"- **00:01** — 첫 해설\n- **00:01** — 둘째 해설\n"
	)
	assert len(log) == 2


def test_review_log_empty_export_still_carries_disclaimer():
	# Even an empty note must be marked machine-generated.
	md = ReviewLog(title="빈 세션").to_markdown()
	assert md.startswith("# 빈 세션\n\n> ⚠️ ")
	assert "AI가 화면을 보고 자동 생성" in md
	assert "_해설 기록이 없습니다._" in md


def test_review_log_provenance_header_lists_provider_and_model():
	log = ReviewLog(title="세션", clock=lambda: "12:00", provider="anthropic", model="claude-opus-4-8")
	log.record("해설")
	md = log.to_markdown()
	assert "> 제공자: anthropic · 모델: claude-opus-4-8 · 생성: 12:00" in md


def test_review_log_omits_provenance_line_when_unknown():
	# No provider/model/clock → disclaimer only, no empty attribution line.
	log = ReviewLog(title="세션")
	log.record("해설")
	md = log.to_markdown()
	assert "제공자" not in md and "모델" not in md and "생성:" not in md
	# The blank quote separator between disclaimer and attribution is not emitted.
	assert ">\n>" not in md


def test_engine_appends_to_review_log():
	log = ReviewLog(clock=lambda: "T")
	engine = NarrationEngine(FixedProvider("체력이 줄었습니다."), Profile(name="t"), review_log=log)
	engine.narrate(_png())
	assert len(log) == 1
	assert log.entries[0].text == "체력이 줄었습니다."


def test_engine_stream_appends_full_narration_to_log():
	log = ReviewLog(clock=lambda: "T")
	engine = NarrationEngine(FixedProvider("한 조각 해설."), Profile(name="t"), review_log=log)
	list(engine.narrate_stream(_png()))
	assert len(log) == 1
	assert log.entries[0].text == "한 조각 해설."


def test_profile_observe_interval_default_and_from_yaml(tmp_path):
	assert Profile(name="x").observe_interval == 1.5
	p = tmp_path / "p.yaml"
	p.write_text("name: lecture\nobserve_interval: 3.0\n", encoding="utf-8")
	assert Profile.from_yaml(p).observe_interval == 3.0
