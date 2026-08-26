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
from bitgil_core.providers import ollama_provider, omniroute_provider
from bitgil_core.providers.ollama_provider import OllamaProvider
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
		self.closed = False

	def close(self):
		self.closed = True

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


@pytest.fixture(autouse=True)
def _no_gateway_token_in_env(monkeypatch):
	# The adapter falls back to these when no key is passed; a developer who has one
	# exported must not get different test results from CI.
	for var in ("OMNIROUTE_API_KEY", "BITGIL_API_KEY"):
		monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_unexpected_model_lookup(monkeypatch):
	# Rerouting fetches /v1/models. A test that triggers it without saying so would
	# otherwise reach for a real gateway on the developer's machine.
	def forbidden(url, **kwargs):
		raise AssertionError(f"unexpected GET {url} — this test didn't expect a reroute")

	monkeypatch.setattr(omniroute_provider.requests, "get", forbidden)


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
	# Pinned model: the user chose this route, so its error is the answer (no reroute).
	payload = {"error": {"message": "[403]: insufficient quota [oc/mimo-v2.5-free]",
	                     "code": "insufficient_quota"}}
	p = OmniRouteProvider(model="oc/mimo-v2.5-free")
	_capture_post(monkeypatch, _FakeResponse(status_code=403, payload=payload))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "insufficient quota" in str(excinfo.value)
	assert "403" in str(excinfo.value)


def test_omniroute_error_without_json_body_still_raises(monkeypatch):
	p = OmniRouteProvider(model="oc/mimo-v2.5-free")
	_capture_post(monkeypatch, _FakeResponse(status_code=502, text="<html>bad gateway</html>"))
	with pytest.raises(requests.HTTPError):
		p.complete([Message(role="user", text="hi")])


def test_omniroute_connection_refused_is_one_spoken_sentence(monkeypatch):
	# The web backend answers a failed frame with {"text": "오류: <exception>"} and the
	# client speaks it, so a raw urllib3 dump ("HTTPConnectionPool(host='localhost',
	# port=20128): Max retries exceeded with url: ...") lands in the user's ear.
	p = OmniRouteProvider()

	def refuse(url, **kwargs):
		raise requests.ConnectionError(
			"HTTPConnectionPool(host='localhost', port=20128): Max retries exceeded "
			"with url: /v1/chat/completions (Caused by NewConnectionError(...))"
		)

	monkeypatch.setattr(omniroute_provider.requests, "post", refuse)
	with pytest.raises(requests.ConnectionError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	spoken = str(excinfo.value)
	assert "HTTPConnectionPool" not in spoken and "Max retries" not in spoken
	assert "OmniRoute 게이트웨이에 연결할 수 없습니다" in spoken
	assert "http://localhost:20128/v1" in spoken   # which endpoint was tried
	assert spoken.count("\n") == 0                 # one sentence, not a traceback


def test_ollama_connection_refused_names_the_fix(monkeypatch):
	# Same failure mode as the gateway: `ollama serve` not running.
	p = OllamaProvider(model="llava")

	def refuse(url, **kwargs):
		raise requests.ConnectionError("HTTPConnectionPool(host='localhost', port=11434): ...")

	monkeypatch.setattr(ollama_provider.requests, "post", refuse)
	with pytest.raises(requests.ConnectionError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	spoken = str(excinfo.value)
	assert "HTTPConnectionPool" not in spoken
	assert "Ollama에 연결할 수 없습니다" in spoken
	assert "ollama serve" in spoken and "llava" in spoken


def test_timeout_becomes_readable_too(monkeypatch):
	p = OmniRouteProvider()

	def stall(url, **kwargs):
		raise requests.Timeout("HTTPSConnectionPool(...): Read timed out. (read timeout=120)")

	monkeypatch.setattr(omniroute_provider.requests, "post", stall)
	with pytest.raises(requests.Timeout) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "제때 응답하지 않았습니다" in str(excinfo.value)
	assert "Read timed out" not in str(excinfo.value)


def test_http_errors_still_pass_through_unchanged(monkeypatch):
	# The wrapper must not swallow HTTP errors — the gateway's own 429 text is more
	# specific than anything we would substitute.
	payload = {"error": {"message": "[429]: Rate limit exceeded"}}
	p = OmniRouteProvider(model="oc/mimo-v2.5-free")
	_capture_post(monkeypatch, _FakeResponse(status_code=429, payload=payload))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "Rate limit exceeded" in str(excinfo.value)


# --- OmniRoute: a gated gateway, and a route that can't see images --------------

def _capture_calls(monkeypatch, posts, models_payload=None):
	"""Queue POST responses (last one repeats) and serve GET /models from a payload."""
	calls = {"posts": [], "gets": []}
	queue = list(posts)

	def fake_post(url, **kwargs):
		calls["posts"].append({"url": url, **kwargs})
		return queue.pop(0) if len(queue) > 1 else queue[0]

	def fake_get(url, **kwargs):
		calls["gets"].append({"url": url, **kwargs})
		return _FakeResponse(payload=models_payload or {})

	monkeypatch.setattr(omniroute_provider.requests, "post", fake_post)
	monkeypatch.setattr(omniroute_provider.requests, "get", fake_get)
	return calls


_NO_VISION_TARGET = {"error": {"message": "No target in combo auto/pro-vision has "
                                          "confirmed vision support for this image request"}}

# A combo that claims vision is included on purpose: the combo is what just failed,
# so discovery has to reach past it to a concrete model.
_MODELS = {"data": [
	{"id": "auto/pro-vision", "capabilities": {"reasoning": True}},
	{"id": "auto/best-vision", "capabilities": {"vision": True}},
	{"id": "oc/text-only-free", "capabilities": {"tool_calling": True}},
	{"id": "ddgw/claude-haiku-4-5", "capabilities": {"vision": True}},
]}


def test_omniroute_reads_gateway_token_from_env(monkeypatch):
	# Enabling auth on the gateway must not mean retyping a token to start narrating:
	# OMNIROUTE_API_KEY is the gateway CLI's own variable, so we honour it.
	monkeypatch.setenv("OMNIROUTE_API_KEY", "gw-token")
	seen = _capture_post(monkeypatch, _FakeResponse(payload={"choices": []}))
	build_provider("omniroute").complete([Message(role="user", text="hi")])
	assert seen["headers"]["Authorization"] == "Bearer gw-token"


def test_omniroute_bitgil_api_key_env_also_works(monkeypatch):
	monkeypatch.setenv("BITGIL_API_KEY", "bitgil-token")
	seen = _capture_post(monkeypatch, _FakeResponse(payload={"choices": []}))
	OmniRouteProvider().complete([Message(role="user", text="hi")])
	assert seen["headers"]["Authorization"] == "Bearer bitgil-token"


def test_omniroute_explicit_key_beats_the_environment(monkeypatch):
	monkeypatch.setenv("OMNIROUTE_API_KEY", "from-env")
	seen = _capture_post(monkeypatch, _FakeResponse(payload={"choices": []}))
	OmniRouteProvider(api_key="explicit").complete([Message(role="user", text="hi")])
	assert seen["headers"]["Authorization"] == "Bearer explicit"


def test_omniroute_401_names_the_variable_that_fixes_it(monkeypatch):
	# "Authentication required" read aloud tells the user nothing to do.
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(status_code=401,
	                                         payload={"error": {"message": "Authentication required"}}))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "OMNIROUTE_API_KEY" in str(excinfo.value)


def test_omniroute_403_quota_is_not_reported_as_an_auth_problem(monkeypatch):
	# The gateway also uses 403 for an exhausted upstream quota; an auth hint there
	# would send the user off to mint a token that changes nothing.
	p = OmniRouteProvider(model="oc/mimo-v2.5-free")
	_capture_post(monkeypatch, _FakeResponse(
		status_code=403, payload={"error": {"message": "[403]: insufficient quota"}}))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "OMNIROUTE_API_KEY" not in str(excinfo.value)
	assert "insufficient quota" in str(excinfo.value)


def test_omniroute_recovers_from_a_combo_with_no_vision_target(monkeypatch):
	# Live 400 on a fresh gateway: the combo resolved to text-only upstreams. Every
	# Bitgil call is a screenshot, so instead of speaking the 400 we ask the gateway
	# which model can see, and retry on it.
	ok = _FakeResponse(payload={"choices": [{"message": {"content": "막대 네 개"}}]})
	calls = _capture_calls(monkeypatch,
	                       [_FakeResponse(status_code=400, payload=_NO_VISION_TARGET), ok],
	                       models_payload=_MODELS)
	p = OmniRouteProvider()
	out = p.complete([Message(role="user", text="설명해줘", image=b"\x89PNG")])
	assert out.text == "막대 네 개"
	assert calls["gets"][0]["url"] == "http://localhost:20128/v1/models"
	# Reached past the combo (even one advertising vision) to a concrete model...
	assert p.model == "ddgw/claude-haiku-4-5"
	assert calls["posts"][1]["json"]["model"] == "ddgw/claude-haiku-4-5"
	# ...and remembers it, so the next frame doesn't pay for the discovery again.
	p.complete([Message(role="user", text="다시", image=b"\x89PNG")])
	assert len(calls["gets"]) == 1


def test_omniroute_pinned_model_is_never_rerouted(monkeypatch):
	# The user asked for this route, so its failure is the answer — silently narrating
	# through a different model than the one they chose would be worse than the error.
	calls = _capture_calls(monkeypatch, [_FakeResponse(
		status_code=400, payload={"error": {"message": "context limit exceeded"}})])
	with pytest.raises(requests.HTTPError):
		OmniRouteProvider(model="oc/mimo-v2.5-free").complete(
			[Message(role="user", text="hi", image=b"\x89PNG")])
	assert len(calls["posts"]) == 1 and calls["gets"] == []


def test_omniroute_never_reroutes_on_an_auth_failure(monkeypatch):
	# No other route fixes a missing token; trying three would just delay the fix.
	calls = _capture_calls(monkeypatch, [_FakeResponse(
		status_code=401, payload={"error": {"message": "Authentication required"}})])
	with pytest.raises(requests.HTTPError):
		OmniRouteProvider().complete([Message(role="user", text="hi", image=b"\x89PNG")])
	assert len(calls["posts"]) == 1 and calls["gets"] == []


def test_omniroute_says_what_to_do_when_no_model_can_see(monkeypatch):
	text_only = {"data": [{"id": "oc/text-free", "capabilities": {"tool_calling": True}}]}
	_capture_calls(monkeypatch, [_FakeResponse(status_code=400, payload=_NO_VISION_TARGET)],
	               models_payload=text_only)
	with pytest.raises(requests.HTTPError) as excinfo:
		OmniRouteProvider().complete([Message(role="user", text="hi", image=b"\x89PNG")])
	spoken = str(excinfo.value)
	assert "이미지를 읽을 수 있는 모델이 없습니다" in spoken
	assert "http://localhost:20128" in spoken   # where to go connect one


def test_omniroute_stream_also_recovers_from_a_vision_incapable_route(monkeypatch):
	streamed = _FakeResponse(lines=[b'data: {"choices":[{"delta":{"content":"\xec\x95\x88"}}]}'])
	_capture_calls(monkeypatch,
	               [_FakeResponse(status_code=400, payload=_NO_VISION_TARGET), streamed],
	               models_payload=_MODELS)
	p = OmniRouteProvider()
	assert list(p.stream([Message(role="user", text="hi", image=b"\x89PNG")])) == ["안"]
	assert p.model == "ddgw/claude-haiku-4-5"


# --- OmniRoute: a vision flag is a claim, not a working route --------------------
#
# Measured on the owner's Mac (2026-08-27) after route discovery shipped: the model it
# picked declared capabilities.vision and still refused the screenshot
# ("DuckDuckGo AI Chat error: ERR_BAD_REQUEST"), and another route answered 429. So one
# lookup isn't enough — a failed route has to hand off to the next candidate.

def _route_calls(monkeypatch, by_model, models_payload):
	"""Answer each POST from `by_model[requested model]`; serve GET /models once."""
	calls = {"models": [], "gets": 0}

	def fake_post(url, **kwargs):
		model = kwargs["json"]["model"]
		calls["models"].append(model)
		return by_model[model]

	def fake_get(url, **kwargs):
		calls["gets"] += 1
		return _FakeResponse(payload=models_payload)

	monkeypatch.setattr(omniroute_provider.requests, "post", fake_post)
	monkeypatch.setattr(omniroute_provider.requests, "get", fake_get)
	return calls


# Widest input capacity first is the order discovery uses, so oc/big precedes ddgw/mid.
_CAPACITY_MODELS = {"data": [
	{"id": "auto/pro-vision", "capabilities": {"vision": True}},        # combo — skipped
	{"id": "ddgw/mid", "capabilities": {"vision": True}, "max_input_tokens": 409600},
	{"id": "oc/big", "capabilities": {"vision": True}, "max_input_tokens": 1048576},
	{"id": "oc/text-only", "capabilities": {"tool_calling": True}},     # no vision — skipped
]}

_BAD_IMAGE_REQUEST = {"error": {"message": "[400]: DuckDuckGo AI Chat error: ERR_BAD_REQUEST"}}
_RATE_LIMITED = {"error": {"message": "[429]: Error from provider (Console): Rate limit "
                                      "exceeded. Please try again later."}}


def test_omniroute_falls_forward_when_a_vision_model_refuses_the_image(monkeypatch):
	ok = _FakeResponse(payload={"choices": [{"message": {"content": "막대 네 개"}}]})
	calls = _route_calls(monkeypatch, {
		"auto/pro-vision": _FakeResponse(status_code=400, payload=_NO_VISION_TARGET),
		"oc/big": _FakeResponse(status_code=400, payload=_BAD_IMAGE_REQUEST),
		"ddgw/mid": ok,
	}, _CAPACITY_MODELS)
	p = build_provider("omniroute", speed="quality")
	out = p.complete([Message(role="user", text="설명해줘", image=b"\x89PNG")])
	assert out.text == "막대 네 개"
	# Widest context first, then on to the next candidate when it refused the image.
	assert calls["models"] == ["auto/pro-vision", "oc/big", "ddgw/mid"]
	assert p.model == "ddgw/mid"
	# The route that can't take an image is dropped for good: the next frame goes
	# straight to the one that worked, and the model list isn't fetched again.
	p.complete([Message(role="user", text="다시", image=b"\x89PNG")])
	assert calls["models"][3:] == ["ddgw/mid"] and calls["gets"] == 1


def test_omniroute_keeps_a_rate_limited_route_for_later(monkeypatch):
	# 429 means "not now", not "never" — quota resets, and that route may be the best
	# one available, so it must not be struck off the list.
	ok = _FakeResponse(payload={"choices": [{"message": {"content": "설명"}}]})
	_route_calls(monkeypatch, {
		"auto/pro-vision": _FakeResponse(status_code=429, payload=_RATE_LIMITED),
		"oc/big": _FakeResponse(status_code=429, payload=_RATE_LIMITED),
		"ddgw/mid": ok,
	}, _CAPACITY_MODELS)
	p = build_provider("omniroute", speed="quality")
	assert p.complete([Message(role="user", text="hi", image=b"\x89PNG")]).text == "설명"
	assert p._dead_models == set()


def test_omniroute_reroutes_when_the_combo_itself_is_rate_limited(monkeypatch):
	# Observed live: the combo's own pool was exhausted (429) rather than vision-blind.
	# A concrete route with quota still gets the user their narration.
	ok = _FakeResponse(payload={"choices": [{"message": {"content": "해설"}}]})
	calls = _route_calls(monkeypatch, {
		"auto/best-vision": _FakeResponse(status_code=429, payload=_RATE_LIMITED),
		"oc/big": ok,
	}, _CAPACITY_MODELS)
	p = OmniRouteProvider()
	assert p.complete([Message(role="user", text="hi", image=b"\x89PNG")]).text == "해설"
	assert calls["models"] == ["auto/best-vision", "oc/big"]


def test_omniroute_reports_every_route_it_tried_when_all_fail(monkeypatch):
	calls = _route_calls(monkeypatch, {
		"auto/pro-vision": _FakeResponse(status_code=400, payload=_NO_VISION_TARGET),
		"oc/big": _FakeResponse(status_code=400, payload=_BAD_IMAGE_REQUEST),
		"ddgw/mid": _FakeResponse(status_code=429, payload=_RATE_LIMITED),
	}, _CAPACITY_MODELS)
	p = build_provider("omniroute", speed="quality")
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi", image=b"\x89PNG")])
	spoken = str(excinfo.value)
	assert "2개를 시도했지만 모두 실패" in spoken     # how much was already tried
	assert "Rate limit exceeded" in spoken           # the last gateway reason survives
	assert "http://localhost:20128" in spoken        # and where to fix it
	assert len(calls["models"]) == 3


def test_omniroute_route_attempts_are_capped(monkeypatch):
	# Each attempt is a round trip inside a narration turn, so the fan-out is bounded.
	many = {"data": [{"id": f"p{i}/m", "capabilities": {"vision": True},
	                  "max_input_tokens": 1000 - i} for i in range(8)]}
	failing = {f"p{i}/m": _FakeResponse(status_code=429, payload=_RATE_LIMITED)
	           for i in range(8)}
	failing["auto/best-vision"] = _FakeResponse(status_code=429, payload=_RATE_LIMITED)
	calls = _route_calls(monkeypatch, failing, many)
	with pytest.raises(requests.HTTPError):
		OmniRouteProvider().complete([Message(role="user", text="hi", image=b"\x89PNG")])
	assert calls["models"] == ["auto/best-vision", "p0/m", "p1/m", "p2/m"]


def test_omniroute_non_json_success_body_raises_readable_error(monkeypatch):
	# Seen live: a 200 whose body isn't JSON. Unguarded, resp.json() surfaces
	# "Expecting value: line 1 column 1" — meaningless when read aloud.
	p = OmniRouteProvider()
	_capture_post(monkeypatch, _FakeResponse(status_code=200, text="<html>proxy</html>"))
	with pytest.raises(requests.HTTPError) as excinfo:
		p.complete([Message(role="user", text="hi")])
	assert "non-JSON" in str(excinfo.value)


def test_omniroute_skips_a_dead_route_on_the_following_frame(monkeypatch):
	# The fall-forward loop leaves `model` on the last route it tried — a dead one when
	# everything failed — so the next frame paid a round trip just to be refused again.
	# That round trip is silence for someone waiting to hear what changed on screen.
	models = {"data": [{"id": f"p{i}/m", "capabilities": {"vision": True},
	                    "max_input_tokens": 900 - i} for i in range(4)]}
	responses = {f"p{i}/m": _FakeResponse(status_code=400, payload=_BAD_IMAGE_REQUEST)
	             for i in range(3)}
	responses["p3/m"] = _FakeResponse(payload={"choices": [{"message": {"content": "살아있다"}}]})
	responses["auto/best-vision"] = _FakeResponse(status_code=400, payload=_NO_VISION_TARGET)
	calls = _route_calls(monkeypatch, responses, models)
	p = OmniRouteProvider()
	frame = [Message(role="user", text="hi", image=b"\x89PNG")]
	with pytest.raises(requests.HTTPError):
		p.complete(frame)                        # the cap stops it before the live route
	assert calls["models"] == ["auto/best-vision", "p0/m", "p1/m", "p2/m"]
	assert p.complete(frame).text == "살아있다"
	assert calls["models"][4:] == ["p3/m"]       # straight there: no dead route retried
	assert calls["gets"] == 1                    # and the catalog is still fetched once


def _fake_models(monkeypatch, payload):
	monkeypatch.setattr(omniroute_provider.requests, "get",
	                    lambda url, **kwargs: _FakeResponse(payload=payload))


def test_omniroute_route_report_ranks_routes_and_marks_the_ones_it_would_try(monkeypatch):
	# `--list-routes` answers "which models did it even try?" — a question only the
	# user's own gateway can answer, since the catalog follows the providers they
	# connected in the dashboard.
	_fake_models(monkeypatch, _CAPACITY_MODELS)
	report = OmniRouteProvider().route_report()
	assert [model_id for model_id, _, _ in report["vision"]] == ["oc/big", "ddgw/mid"]
	assert report["would_try"] == ["oc/big", "ddgw/mid"]
	# The combo is dropped even though it claims vision; the text-only model is *listed*
	# (so the user sees it exists) but is never a candidate for an image.
	assert [model_id for model_id, _, _ in report["models"]] == [
		"ddgw/mid", "oc/big", "oc/text-only"]
	assert report["authenticated"] is False


def test_omniroute_route_report_caps_would_try_at_the_attempt_limit(monkeypatch):
	# What it says it *would* try has to match what it *does* try, or the diagnostic lies.
	_fake_models(monkeypatch, {"data": [{"id": f"p{i}/m", "capabilities": {"vision": True},
	                                     "max_input_tokens": 900 - i} for i in range(6)]})
	report = OmniRouteProvider().route_report()
	assert len(report["vision"]) == 6
	assert report["would_try"] == ["p0/m", "p1/m", "p2/m"]


def test_omniroute_route_report_reports_a_gateway_with_no_vision_model(monkeypatch):
	# The diagnostic must not raise on the very case it exists to explain.
	_fake_models(monkeypatch, {"data": [
		{"id": "auto/best-vision", "capabilities": {"vision": True}},
		{"id": "oc/text-only", "capabilities": {"tool_calling": True}}]})
	report = OmniRouteProvider().route_report()
	assert report["vision"] == []
	assert report["would_try"] == []
	assert report["dashboard"] == "http://localhost:20128"
