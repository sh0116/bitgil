"""Provider adapter interface.

Every concrete provider (OpenAI, Anthropic, Gemini, Ollama) implements
`VisionProvider`. The rest of EyeMate depends only on this interface, so
swapping providers — or adding a local one — never touches call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence


@dataclass
class Message:
	"""One turn of conversation. `image` is raw PNG/JPEG bytes when present."""

	role: str  # "system" | "user" | "assistant"
	text: str = ""
	image: Optional[bytes] = None


@dataclass
class VisionResponse:
	text: str
	# Token/cost accounting so we can honour the transparency promise in the plan.
	prompt_tokens: int = 0
	completion_tokens: int = 0
	extra: dict = field(default_factory=dict)


class VisionProvider(ABC):
	"""Single interface across all vision-LLM backends.

	Implementations should be cheap to construct (no network on __init__) and
	must never log or persist image bytes.
	"""

	name: str = "base"

	@abstractmethod
	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		"""Return a full response for the given messages (blocking)."""

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		"""Yield response text incrementally.

		Streaming matters for latency: F1 narrates sentence-by-sentence as tokens
		arrive rather than waiting for the whole response. Default implementation
		falls back to a single chunk; providers that support SSE should override.
		"""
		yield self.complete(messages, max_tokens=max_tokens).text
