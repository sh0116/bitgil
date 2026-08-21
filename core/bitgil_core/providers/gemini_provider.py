"""Google Gemini vision provider adapter.

Uses the official `google-generativeai` SDK, imported lazily so the module loads
(and the test suite runs) without it. Gemini has no "system" role: system
messages are merged into the model's `system_instruction`, and the remaining
turns become `contents` with roles user / model.
"""

from __future__ import annotations

from typing import Iterator, List, Sequence

from .base import Message, VisionProvider, VisionResponse

# Flash is fast and cheap — the right default for latency-bound live narration.
DEFAULT_MODEL = "gemini-1.5-flash"

# Speed tier → model. Flash for fast/balanced; Pro for quality (chart/graph).
SPEED_MODELS = {
	"fast": "gemini-1.5-flash",
	"balanced": "gemini-1.5-flash",
	"quality": "gemini-1.5-pro",
}


def _to_gemini(messages: Sequence[Message]) -> tuple[str, list[dict]]:
	"""Split our Message list into (system_instruction, gemini contents)."""
	system_parts: List[str] = []
	contents: list[dict] = []
	for m in messages:
		if m.role == "system":
			if m.text:
				system_parts.append(m.text)
			continue
		parts: list = []
		if m.image is not None:
			parts.append({"mime_type": "image/png", "data": m.image})
		if m.text:
			parts.append(m.text)
		# Gemini uses "model" for the assistant turn; "user" otherwise.
		role = "model" if m.role == "assistant" else "user"
		contents.append({"role": role, "parts": parts or [m.text]})
	return "\n\n".join(system_parts), contents


def _safe_text(resp) -> str:
	"""Extract text from a Gemini response without raising.

	The SDK's ``resp.text`` shortcut raises ValueError when the response carries
	no usable Part — e.g. the candidate was blocked by a safety filter or stopped
	for a non-STOP reason. For an accessibility tool that would crash a narration
	mid-session, so fall back to stitching candidate parts and finally to "".
	"""
	try:
		return resp.text or ""
	except (ValueError, AttributeError):
		pass
	pieces: List[str] = []
	for cand in getattr(resp, "candidates", None) or []:
		content = getattr(cand, "content", None)
		for part in getattr(content, "parts", None) or []:
			text = getattr(part, "text", "")
			if text:
				pieces.append(text)
	return "".join(pieces)


class GeminiProvider(VisionProvider):
	name = "gemini"
	SPEED_MODELS = SPEED_MODELS

	def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
		self._api_key = api_key
		self.model = model
		self._client = None
		self._client_system = None  # system_instruction the cached client was built with
		self._configured = False

	def _get_model(self, system_instruction: str):
		"""Build (and cache) a GenerativeModel for a given system prompt.

		The system_instruction is baked into the GenerativeModel at construction,
		so the cache must be keyed on it: a single provider instance is shared
		across different system prompts (e.g. narration vs. interruption triage in
		the web backend), and reusing a model built with the wrong system prompt
		would silently apply the wrong instructions. Rebuild when it changes."""
		import google.generativeai as genai  # lazy: only needed when calling out

		if not self._configured:
			genai.configure(api_key=self._api_key)
			self._configured = True
		system = system_instruction or None
		if self._client is None or self._client_system != system:
			self._client = genai.GenerativeModel(self.model, system_instruction=system)
			self._client_system = system
		return self._client

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		system, contents = _to_gemini(messages)
		resp = self._get_model(system).generate_content(
			contents,
			generation_config={"max_output_tokens": max_tokens},
		)
		usage = getattr(resp, "usage_metadata", None)
		return VisionResponse(
			text=_safe_text(resp),
			prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
			completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
		)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		system, contents = _to_gemini(messages)
		stream = self._get_model(system).generate_content(
			contents,
			generation_config={"max_output_tokens": max_tokens},
			stream=True,
		)
		for chunk in stream:
			piece = getattr(chunk, "text", "")
			if piece:
				yield piece
