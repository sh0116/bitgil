"""Provider-adapter robustness tests (offline, SDKs faked).

These don't hit any network: they inject fakes for the OpenAI client and the
google-generativeai module so the adapters' fragile spots — streaming chunks with
no choices, Gemini's system-prompt caching, and its raising ``resp.text`` — are
exercised deterministically.
"""

import sys
import types

import pytest
import requests

from bitgil_core.providers import build_provider
from bitgil_core.providers.base import Message
from bitgil_core.providers.demo_provider import DemoProvider
from bitgil_core.providers.gemini_provider import GeminiProvider, _safe_text
from bitgil_core.providers.openai_provider import OpenAIProvider
from bitgil_core.providers import omniroute_provider
from bitgil_core.providers.omniroute_provider import OmniRouteProvider


# --- Demo provider: keyless, rotates, routed through the factory -------------

def test_factory_builds_demo_without_credentials():
	# No config, no api_key — the factory must return a working demo provider.
	p = build_provider("demo")
	assert isinstance(p, DemoProvider)
	assert p.name == "demo"


def test_demo_provider_rotates_nonempty_korean():
	p = DemoProvider()
	msgs = [Message(role="user", text="hi")]
	first = p.complete(msgs).text
	second = p.complete(msgs).text
	assert first and second and first != second   # rotates each call
	assert first.startswith("(데모)")


def test_demo_provider_stream_yields_text():
	p = DemoProvider()
	out = list(p.stream([Message(role="user", text="hi")]))
	assert out and out[0].startswith("(데모)")


# --- OpenAI: streaming must tolerate choice-less chunks ----------------------

class _Delta:
	def __init__(self, content):
		self.content = content


class _Choice:
	def __init__(self, content):
		self.delta = _Delta(content)


class _Chunk:
	def __init__(self, choices):
		self.choices = choices


class _FakeCompletions:
	def __init__(self, chunks):
		self._chunks = chunks

	def create(self, **kwargs):
		return iter(self._chunks)


class _FakeClient:
	def __init__(self, chunks):
		self.chat = types.SimpleNamespace(completions=_FakeCompletions(chunks))


def test_openai_stream_skips_chunks_without_choices():
	# The trailing usage-only chunk (include_usage) carries no choices; indexing
	# [0] there used to raise IndexError and kill the stream.
	chunks = [
		_Chunk([_Choice("안녕")]),
		_Chunk([]),               # usage-only chunk — no choices
		_Chunk([_Choice("하세요")]),
		_Chunk([_Choice(None)]),  # empty delta
	]
	p = OpenAIProvider(api_key="x")
	p._client = _FakeClient(chunks)
	out = list(p.stream([Message(role="user", text="hi")]))
	assert out == ["안녕", "하세요"]


# --- Gemini: _safe_text never raises -----------------------------------------

class _RaisingText:
	@property
	def text(self):
		raise ValueError("no valid Part — blocked by safety filter")


class _RaisingWithCandidates:
	"""resp.text raises (blocked candidate), but usable parts exist to fall back to."""

	def __init__(self, *texts):
		parts = [types.SimpleNamespace(text=t) for t in texts]
		self.candidates = [types.SimpleNamespace(content=types.SimpleNamespace(parts=parts))]

	@property
	def text(self):
		raise ValueError("no valid Part — blocked by safety filter")


def test_safe_text_falls_back_to_candidate_parts():
	assert _safe_text(_RaisingWithCandidates("후보 ", "텍스트")) == "후보 텍스트"


def test_safe_text_returns_empty_when_nothing_usable():
	assert _safe_text(_RaisingText()) == ""


# --- Gemini: model cache must key on the system prompt -----------------------

class _FakeGenerativeModel:
	instances = []

	def __init__(self, model, system_instruction=None):
		self.model = model
		self.system_instruction = system_instruction
		_FakeGenerativeModel.instances.append(self)


def _install_fake_genai(monkeypatch_modules):
	fake = types.ModuleType("google.generativeai")
	fake.configure = lambda **kw: None
	fake.GenerativeModel = _FakeGenerativeModel
	google_pkg = types.ModuleType("google")
	google_pkg.generativeai = fake
	monkeypatch_modules["google"] = google_pkg
	monkeypatch_modules["google.generativeai"] = fake


def test_gemini_rebuilds_model_when_system_prompt_changes():
	_FakeGenerativeModel.instances = []
	saved = {k: sys.modules.get(k) for k in ("google", "google.generativeai")}
	try:
		_install_fake_genai(sys.modules)
		p = GeminiProvider(api_key="x")
		p._get_model("system A")
		p._get_model("system A")   # same prompt → reuse, no new instance
		p._get_model("system B")   # different prompt → must rebuild
		systems = [m.system_instruction for m in _FakeGenerativeModel.instances]
		assert systems == ["system A", "system B"]
	finally:
		for k, v in saved.items():
			if v is None:
				sys.modules.pop(k, None)
			else:
				sys.modules[k] = v


# --- OmniRoute: keyless gateway, OpenAI wire format, SSE ---------------------

class _FakeResponse:
	"""Minimal stand-in for requests.Response (also usable as a context manager)."""

	def __init__(self, status_code=200, payload=None, lines=(), text=""):
		self.status_code = status_code
		self._payload = payload
		self._lines = lines
		self.text = text

	def json(self):
		if self._payload is None:
			raise ValueError("not json")
		return self._payload

	def iter_lines(self):
		return iter(self._lines)

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		return False


def _capture_post(monkeypatch, response):
	"""Point the adapter's requests.post at `response`, recording the call."""
	seen = {}

	def fake_post(url, **kwargs):
		seen["url"] = url
		seen.update(kwargs)
		return response

	monkeypatch.setattr(omniroute_provider.requests, "post", fake_post)
	return seen


def test_factory_builds_omniroute_keyless_with_vision_default():
	# No config at all: keyless local gateway, vision-capable combo channel.
	p = build_provider("omniroute")
	assert isinstance(p, OmniRouteProvider)
	assert p.name == "omniroute"
	assert p.model == "auto/best-vision"
	assert p.base_url == "http://localhost:20128/v1"
	assert p._api_key is None


def test_omniroute_speed_tiers_stay_on_image_capable_channels():
	# Every Bitgil call carries a screenshot, and the plain auto/vision and
	# auto/multimodal channels reject one (candidate context too small on a live
	# gateway), so no tier may resolve to them.
	tiers = {t: build_provider("omniroute", speed=t).model
	         for t in ("fast", "balanced", "quality")}
	assert tiers == {"fast": "auto/best-vision", "balanced": "auto/best-vision",
	                 "quality": "auto/pro-vision"}
	# An explicit model always wins over the tier.
	# An explicit model always wins over the tier.
	pinned = build_provider("omniroute", {"model": "aug/haiku4.5"}, speed="quality")
	assert pinned.model == "aug/haiku4.5"


def test_omniroute_config_threads_base_url_and_key(monkeypatch):
	p = build_provider("omniroute", {"base_url": "http://box:20128/v1/", "api_key": "tok"})
	assert p.base_url == "http://box:20128/v1"     # trailing slash trimmed
	seen = _capture_post(monkeypatch, _FakeResponse(payload={"choices": []}))
	p.complete([Message(role="user", text="hi")])
	assert seen["url"] == "http://box:20128/v1/chat/completions"
	assert seen["headers"]["Authorization"] == "Bearer tok"


def test_omniroute_keyless_sends_no_auth_header(monkeypatch):
	p = OmniRouteProvider()
	seen = _capture_post(monkeypatch, _FakeResponse(payload={"choices": []}))
	p.complete([Message(role="user", text="hi")])
	assert "Authorization" not in seen["headers"]


def test_omniroute_complete_parses_text_usage_and_served_model(monkeypatch):
	payload = {
		"model": "aug/haiku4.5",          # combo channel resolved to a real upstream
		"choices": [{"message": {"content": "막대 네 개가 보입니다."}}],
		"usage": {"prompt_tokens": 12, "completion_tokens": 7},
	}
	p = OmniRouteProvider()
	seen = _capture_post(monkeypatch, _FakeResponse(payload=payload))
	out = p.complete([Message(role="user", text="설명해줘", image=b"\x89PNG_fake")])
	assert out.text == "막대 네 개가 보입니다."
	assert (out.prompt_tokens, out.completion_tokens) == (12, 7)
	# Which upstream actually answered — needed for review-note provenance.
	assert out.extra["served_model"] == "aug/haiku4.5"
	# The screenshot must ride along as an OpenAI-style data URL, or the gateway
	# silently narrates a blank screen.
	content = seen["json"]["messages"][0]["content"]
	assert any(c.get("type") == "image_url" for c in content)


def test_omniroute_complete_survives_empty_choices(monkeypatch):
	# A gateway can answer 200 with no choices; narration should degrade, not crash.
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(payload={"choices": []}))
	assert p.complete([Message(role="user", text="hi")]).text == ""


def test_omniroute_stream_parses_sse_and_skips_noise(monkeypatch):
	lines = [
		b": keep-alive ping",                                        # SSE comment
		b'data: {"choices":[{"delta":{"content":"\xec\x95\x88\xeb\x85\x95"}}]}',
		b"",                                                          # blank separator
		b"data: {truncated",                                          # malformed frame
		b'data: {"choices":[]}',                                      # usage-only chunk
		b'data: {"choices":[{"delta":{}}]}',                          # no content key
		b'data: {"choices":[{"delta":{"content":"\xed\x95\x98\xec\x84\xb8\xec\x9a\x94"}}]}',
		b"data: [DONE]",
	]
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(lines=lines))
	assert list(p.stream([Message(role="user", text="hi")])) == ["안녕", "하세요"]


def test_omniroute_error_surfaces_gateway_detail(monkeypatch):
	# An exhausted free pool must reach the user as its cause, not a bare 403.
	payload = {"error": {"message": "[403]: insufficient quota [oc/mimo-v2.5-free]",
	                     "code": "insufficient_quota"}}
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(status_code=403, payload=payload))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "insufficient quota" in str(excinfo.value)
	assert "403" in str(excinfo.value)


def test_omniroute_error_without_json_body_still_raises(monkeypatch):
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(status_code=502, text="<html>bad gateway</html>"))
	with pytest.raises(requests.HTTPError):
		p.complete([Message(role="user", text="hi")])


def test_omniroute_non_json_success_body_raises_readable_error(monkeypatch):
	# Seen live: a 200 whose body isn't JSON. Unguarded, resp.json() surfaces
	# "Expecting value: line 1 column 1" — meaningless when read aloud.
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(status_code=200, text="<html>proxy</html>"))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "non-JSON" in str(excinfo.value)
