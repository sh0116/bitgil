"""OpenAI (GPT) vision provider adapter.

Uses the official `openai` SDK, imported lazily so the module loads without it.
"""

from __future__ import annotations

import base64
from typing import Iterator, Sequence

from .base import Message, VisionProvider, VisionResponse

DEFAULT_MODEL = "gpt-4o-mini"  # a fast, low-cost vision model; override via config


def _to_openai(messages: Sequence[Message]) -> list[dict]:
	converted: list[dict] = []
	for m in messages:
		if m.image is not None:
			b64 = base64.standard_b64encode(m.image).decode("ascii")
			content: list[dict] = []
			if m.text:
				content.append({"type": "text", "text": m.text})
			content.append(
				{
					"type": "image_url",
					"image_url": {"url": f"data:image/png;base64,{b64}"},
				}
			)
			converted.append({"role": m.role, "content": content})
		else:
			converted.append({"role": m.role, "content": m.text})
	return converted


class OpenAIProvider(VisionProvider):
	name = "openai"

	def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
		self._api_key = api_key
		self.model = model
		self._client = None

	def _get_client(self):
		if self._client is None:
			import openai

			self._client = openai.OpenAI(api_key=self._api_key)
		return self._client

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		resp = self._get_client().chat.completions.create(
			model=self.model,
			max_tokens=max_tokens,
			messages=_to_openai(messages),
		)
		usage = resp.usage
		return VisionResponse(
			text=resp.choices[0].message.content or "",
			prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
			completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
		)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		stream = self._get_client().chat.completions.create(
			model=self.model,
			max_tokens=max_tokens,
			messages=_to_openai(messages),
			stream=True,
		)
		for chunk in stream:
			delta = chunk.choices[0].delta.content
			if delta:
				yield delta
