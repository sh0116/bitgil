"""Anthropic (Claude) vision provider adapter.

Uses the official `anthropic` SDK. The SDK is imported lazily inside methods so
that importing this module (and running the test suite) does not require the
package to be installed.
"""

from __future__ import annotations

import base64
from typing import Iterator, List, Sequence

from .base import Message, VisionProvider, VisionResponse

# Default to the latest capable Claude model. Latency-sensitive profiles can
# override this via the factory / config (e.g. a faster small model).
DEFAULT_MODEL = "claude-opus-4-8"

# Speed tier → model. Live game/lecture narration is latency-bound by the LLM
# round-trip, so a "fast" profile drops to Haiku; "quality" keeps Opus for
# detailed chart/graph description where correctness matters more than speed.
SPEED_MODELS = {
	"fast": "claude-haiku-4-5-20251001",
	"balanced": "claude-sonnet-5",
	"quality": "claude-opus-4-8",
}


def _to_anthropic(messages: Sequence[Message]) -> tuple[str, list[dict]]:
	"""Split our Message list into (system_prompt, anthropic_messages)."""
	system_parts: List[str] = []
	converted: list[dict] = []
	for m in messages:
		if m.role == "system":
			if m.text:
				system_parts.append(m.text)
			continue
		blocks: list[dict] = []
		if m.image is not None:
			blocks.append(
				{
					"type": "image",
					"source": {
						"type": "base64",
						"media_type": "image/png",
						"data": base64.standard_b64encode(m.image).decode("ascii"),
					},
				}
			)
		if m.text:
			blocks.append({"type": "text", "text": m.text})
		converted.append({"role": m.role, "content": blocks or m.text})
	return "\n\n".join(system_parts), converted


class AnthropicProvider(VisionProvider):
	name = "anthropic"
	SPEED_MODELS = SPEED_MODELS

	def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
		self._api_key = api_key
		self.model = model
		self._client = None

	def _get_client(self):
		if self._client is None:
			import anthropic  # lazy: only needed when actually calling out

			self._client = anthropic.Anthropic(api_key=self._api_key)
		return self._client

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		system, msgs = _to_anthropic(messages)
		resp = self._get_client().messages.create(
			model=self.model,
			max_tokens=max_tokens,
			system=system or None,
			messages=msgs,
		)
		text = "".join(b.text for b in resp.content if b.type == "text")
		return VisionResponse(
			text=text,
			prompt_tokens=resp.usage.input_tokens,
			completion_tokens=resp.usage.output_tokens,
		)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		system, msgs = _to_anthropic(messages)
		with self._get_client().messages.stream(
			model=self.model,
			max_tokens=max_tokens,
			system=system or None,
			messages=msgs,
		) as stream:
			yield from stream.text_stream
