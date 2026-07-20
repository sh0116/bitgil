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


class GeminiProvider(VisionProvider):
	name = "gemini"
	SPEED_MODELS = SPEED_MODELS

	def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
		self._api_key = api_key
		self.model = model
		self._client = None

	def _get_model(self, system_instruction: str):
		"""Build (and cache) a GenerativeModel. The system prompt is fixed per
		profile, so caching by construction is fine for a session."""
		import google.generativeai as genai  # lazy: only needed when calling out

		if self._client is None:
			genai.configure(api_key=self._api_key)
			self._client = genai.GenerativeModel(
				self.model, system_instruction=system_instruction or None
			)
		return self._client

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		system, contents = _to_gemini(messages)
		resp = self._get_model(system).generate_content(
			contents,
			generation_config={"max_output_tokens": max_tokens},
		)
		usage = getattr(resp, "usage_metadata", None)
		return VisionResponse(
			text=resp.text or "",
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
