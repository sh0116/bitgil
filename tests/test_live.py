"""Tests for the M2 live-narration loop and sentence aggregation (offline)."""

import io

from PIL import Image

from bitgil_core.change_detect import ChangeDetector
from bitgil_core.engine import NarrationEngine
from bitgil_core.live import LiveNarrator
from bitgil_core.postprocess import iter_sentences
from bitgil_core.profiles import Profile
from bitgil_core.providers.base import VisionProvider, VisionResponse


class StreamProvider(VisionProvider):
	name = "stream-fake"

	def __init__(self, chunks):
		self.chunks = chunks

	def complete(self, messages, *, max_tokens=300):
		return VisionResponse(text="".join(self.chunks))

	def stream(self, messages, *, max_tokens=300):
		yield from self.chunks


def _png(color, size=(64, 64)) -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", size, color).save(buf, format="PNG")
	return buf.getvalue()


def _checkerboard() -> bytes:
	img = Image.new("RGB", (64, 64), "black")
	for x in range(64):
		for y in range(64):
			if (x // 4 + y // 4) % 2 == 0:
				img.putpixel((x, y), (255, 255, 255))
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


# --- sentence aggregation ---------------------------------------------------

def test_iter_sentences_splits_on_boundaries():
	chunks = ["카드가 ", "제시되었", "습니다. 체력이 ", "줄었습니다."]
	assert list(iter_sentences(chunks)) == ["카드가 제시되었습니다.", "체력이 줄었습니다."]


def test_iter_sentences_flushes_trailing_text():
	assert list(iter_sentences(["끝맺음 없는 ", "문장"])) == ["끝맺음 없는 문장"]


def test_iter_sentences_handles_ascii_and_cjk_enders():
	assert list(iter_sentences(["A! ", "B? ", "C"])) == ["A!", "B?", "C"]


def test_iter_sentences_keeps_decimals_intact():
	# The period inside a decimal must NOT split the number — this is the core
	# math/chart scenario (수식 낭독). Chunk boundaries deliberately fall on the dot.
	chunks = ["최댓값은 ", "3.5", "입니다. ", "기울기는 약 ", "1.25", "배."]
	assert list(iter_sentences(chunks)) == ["최댓값은 3.5입니다.", "기울기는 약 1.25배."]


def test_iter_sentences_waits_across_chunk_for_decimal():
	# A period at the very end of a chunk is ambiguous until the next chunk shows
	# a digit follows → the two chunks join into one number, not two sentences.
	assert list(iter_sentences(["원주율은 3.", "14입니다."])) == ["원주율은 3.14입니다."]


def test_iter_sentences_keeps_ellipsis_intact():
	# "..." must not spray "." "." fragments; it stays with its sentence.
	assert list(iter_sentences(["잠시만요...", " 계속합니다."])) == ["잠시만요...", "계속합니다."]


def test_iter_sentences_period_ending_a_chunk_still_splits():
	# A genuine sentence-final period at a chunk edge still splits once the next
	# char proves it isn't a decimal.
	assert list(iter_sentences(["끝.", " 다음."])) == ["끝.", "다음."]


# --- live loop --------------------------------------------------------------

def _engine(chunks):
	profile = Profile(name="t", system_prompt="설명", glossary={"HP": "체력"})
	return NarrationEngine(StreamProvider(chunks), profile)


def test_stream_applies_glossary_across_chunk_boundary():
	# A glossary term split across streamed chunks ("H" + "P") must still be
	# substituted in F1 — the engine now aggregates to sentences before glossary.
	profile = Profile(name="t", system_prompt="s", glossary={"HP": "체력", "Strength": "힘"})
	engine = NarrationEngine(
		StreamProvider(["현재 ", "H", "P", "가 낮고 ", "Str", "ength", "가 높습니다."]), profile
	)
	assert list(engine.narrate_stream(b"img")) == ["현재 체력가 낮고 힘가 높습니다."]


def test_stream_and_nonstream_glossary_agree():
	# F1 (stream) and F2 (blocking) must produce the same substituted text even
	# when the provider fragments a glossary term across chunks.
	chunks = ["H", "P", " 회복. ", "Str", "ength", " 증가."]
	profile = Profile(name="t", system_prompt="s", glossary={"HP": "체력", "Strength": "힘"})
	streamed = " ".join(NarrationEngine(StreamProvider(chunks), profile).narrate_stream(b"img"))
	blocking = NarrationEngine(StreamProvider(chunks), profile).narrate(b"img").text
	assert "HP" not in streamed and "Strength" not in streamed
	assert streamed == blocking == "체력 회복. 힘 증가."


def test_poll_narrates_on_change_and_speaks_sentences():
	spoken = []
	narrator = LiveNarrator(
		engine=_engine(["카드 3장이 ", "제시됨. HP ", "감소."]),
		detector=ChangeDetector(hash_threshold=0.1),
		capture=lambda: _png("black"),
		speak=spoken.append,
	)
	result = narrator.poll()
	# glossary applied (HP -> 체력), split into two sentences
	assert spoken == ["카드 3장이 제시됨.", "체력 감소."]
	assert result == "카드 3장이 제시됨. 체력 감소."


def test_poll_returns_none_when_screen_unchanged():
	frames = [_png("black"), _png("black")]
	spoken = []
	narrator = LiveNarrator(
		engine=_engine(["무언가."]),
		detector=ChangeDetector(hash_threshold=0.1),
		capture=lambda: frames.pop(0),
		speak=spoken.append,
	)
	assert narrator.poll() is not None   # first frame is always new
	assert narrator.poll() is None       # identical second frame → gated out
	assert spoken == ["무언가."]          # spoken exactly once


def test_incremental_context_carries_between_polls():
	# Second narration should see the first in its message history → "what changed".
	engine = _engine(["첫 해설."])
	frames = [_png("black"), _checkerboard()]
	narrator = LiveNarrator(
		engine=engine,
		detector=ChangeDetector(hash_threshold=0.1),
		capture=lambda: frames.pop(0),
		speak=lambda _s: None,
	)
	narrator.poll()
	# Swap the provider's next output and confirm history is included.
	captured_messages = {}
	engine.provider.stream = lambda messages, *, max_tokens=300: (
		captured_messages.setdefault("msgs", list(messages)),
		iter(["둘째 해설."]),
	)[1]
	narrator.poll()
	system_texts = " ".join(m.text for m in captured_messages["msgs"] if m.role == "system")
	assert "첫 해설." in system_texts   # prior narration fed back as context
