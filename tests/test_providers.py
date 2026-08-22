"""Provider-adapter robustness tests (offline, SDKs faked).

These don't hit any network: they inject fakes for the OpenAI client and the
google-generativeai module so the adapters' fragile spots — streaming chunks with
no choices, Gemini's system-prompt caching, and its raising ``resp.text`` — are
exercised deterministically.
"""

import sys
import types

from bitgil_core.providers import build_provider
from bitgil_core.providers.base import Message
from bitgil_core.providers.demo_provider import DemoProvider
from bitgil_core.providers.gemini_provider import GeminiProvider, _safe_text
from bitgil_core.providers.openai_provider import OpenAIProvider


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
