"""Tests for the M1 pipeline: provider factory, narration engine, change detector.

All run offline — the provider is a fake, images are generated in-memory.
"""

import io

import pytest
from PIL import Image

from eyemate_core.change_detect import ChangeDetector
from eyemate_core.engine import NarrationEngine
from eyemate_core.profiles import Profile
from eyemate_core.providers import build_provider
from eyemate_core.providers.base import Message, VisionProvider, VisionResponse


class FakeProvider(VisionProvider):
	"""Records the messages it was called with and returns canned text."""

	name = "fake"

	def __init__(self, reply="HP is high", chunks=None):
		self.reply = reply
		self.chunks = chunks or ["HP ", "is ", "high"]
		self.last_messages = None

	def complete(self, messages, *, max_tokens=300):
		self.last_messages = list(messages)
		return VisionResponse(text=self.reply, prompt_tokens=11, completion_tokens=3)

	def stream(self, messages, *, max_tokens=300):
		self.last_messages = list(messages)
		yield from self.chunks


def _png(color, size=(64, 64)) -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", size, color).save(buf, format="PNG")
	return buf.getvalue()


# --- factory ----------------------------------------------------------------

def test_factory_unknown_provider_raises():
	with pytest.raises(ValueError):
		build_provider("does-not-exist")


def test_factory_planned_provider_raises_not_implemented():
	with pytest.raises(NotImplementedError):
		build_provider("gemini")


def test_factory_builds_ollama_without_sdk():
	# Ollama needs no external SDK (uses requests) — should construct cleanly.
	p = build_provider("ollama", {"model": "llava", "base_url": "http://x:1"})
	assert p.name == "ollama"
	assert p.model == "llava"


# --- engine -----------------------------------------------------------------

def _profile(**kw):
	base = dict(name="t", system_prompt="watch the screen", glossary={"HP": "체력"})
	base.update(kw)
	return Profile(**base)


def test_engine_applies_glossary_and_records_context():
	fake = FakeProvider(reply="HP is high")
	engine = NarrationEngine(fake, _profile())
	out = engine.narrate(_png("red"))
	assert out.text == "체력 is high"          # glossary applied
	assert out.prompt_tokens == 11
	assert engine.context.recent() == ["체력 is high"]  # recorded for incremental narration


def test_engine_sends_profile_prompt_and_image():
	fake = FakeProvider()
	engine = NarrationEngine(fake, _profile())
	engine.narrate(_png("blue"), question="what is my HP?")
	roles = [m.role for m in fake.last_messages]
	assert roles[0] == "system"
	user = fake.last_messages[-1]
	assert isinstance(user, Message)
	assert user.image is not None and user.text == "what is my HP?"


def test_engine_brief_density_caps_length():
	long_reply = "문장 하나입니다. " + "아주 긴 부가 설명이 계속 이어집니다. " * 20
	engine = NarrationEngine(FakeProvider(reply=long_reply), _profile(narration_density="brief"))
	out = engine.narrate(_png("green"))
	assert len(out.text) <= 120


def test_engine_stream_yields_and_records():
	fake = FakeProvider(chunks=["체 ", "력 ", "높음"])
	engine = NarrationEngine(fake, _profile())
	got = list(engine.narrate_stream(_png("red")))
	assert "".join(got) == "체 력 높음"
	assert engine.context.recent() == ["체 력 높음"]


# --- change detector --------------------------------------------------------

def test_change_detector_first_frame_is_change():
	det = ChangeDetector()
	assert det.evaluate(_png("black")).changed is True


def test_change_detector_identical_frame_not_changed():
	det = ChangeDetector()
	frame = _png("black")
	det.evaluate(frame)
	assert det.evaluate(frame).changed is False


def test_change_detector_large_visual_change_detected():
	det = ChangeDetector(hash_threshold=0.1)
	det.evaluate(_png("black"))
	# A fine checkerboard is high-frequency — pHash differs sharply from a solid
	# fill, unlike a single half/half split which pHash treats as near-identical.
	img = Image.new("RGB", (64, 64), "black")
	for x in range(64):
		for y in range(64):
			if (x // 4 + y // 4) % 2 == 0:
				img.putpixel((x, y), (255, 255, 255))
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	res = det.evaluate(buf.getvalue())
	assert res.changed is True
	assert res.reason == "visual"


def test_change_detector_ocr_triggers_on_text_change():
	texts = iter(["HP 72", "HP 58"])
	det = ChangeDetector(hash_threshold=0.99, ocr=lambda _frame: next(texts))
	frame = _png("black")
	det.evaluate(frame)              # first frame, seeds OCR text
	res = det.evaluate(frame)        # identical image, but OCR text changed
	assert res.changed is True
	assert res.text_changed is True
	assert res.reason == "text"
