"""NarrationEngine — the screen-reader-agnostic heart of EyeMate.

Given a captured frame and a profile, it assembles the message list (profile
prompt + recent narration history), calls the configured provider, applies
post-processing (glossary + length cap), records the result in session context,
and returns the text to speak. Both F1 (live narration) and F2 (ask the screen)
route through here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .context import SessionContext
from .postprocess import apply_glossary, cap_length
from .profiles import Profile
from .providers.base import VisionProvider

# Narration density → soft character budget for the spoken output.
_DENSITY_MAX_CHARS = {"brief": 120, "normal": 320, "detailed": 800}


@dataclass
class Narration:
	text: str
	prompt_tokens: int = 0
	completion_tokens: int = 0


class NarrationEngine:
	def __init__(self, provider: VisionProvider, profile: Profile, history_size: int = 5):
		self.provider = provider
		self.profile = profile
		self.context = SessionContext(profile.system_prompt, history_size=history_size)

	def _max_chars(self) -> int:
		return _DENSITY_MAX_CHARS.get(self.profile.narration_density, 320)

	def _finish(self, raw: str) -> str:
		"""Apply glossary substitution and length capping to raw model text."""
		text = apply_glossary(raw, self.profile.glossary)
		return cap_length(text, self._max_chars())

	def narrate(self, frame: bytes, question: str = "") -> Narration:
		"""Produce narration for a frame (blocking). `question` drives F2."""
		messages = self.context.build_messages(frame, user_text=question)
		resp = self.provider.complete(messages, max_tokens=self._pick_max_tokens())
		text = self._finish(resp.text)
		self.context.record_narration(text)
		return Narration(
			text=text,
			prompt_tokens=resp.prompt_tokens,
			completion_tokens=resp.completion_tokens,
		)

	def narrate_stream(self, frame: bytes, question: str = "") -> Iterator[str]:
		"""Stream narration sentence-by-sentence for low perceived latency (F1).

		Yields glossary-substituted chunks as they arrive; the full text is
		recorded to context once the stream completes. Length capping is not
		applied mid-stream (it needs the whole text), so streaming honours the
		profile prompt for brevity rather than a hard char cap.
		"""
		messages = self.context.build_messages(frame, user_text=question)
		parts: list[str] = []
		for chunk in self.provider.stream(messages, max_tokens=self._pick_max_tokens()):
			piece = apply_glossary(chunk, self.profile.glossary)
			parts.append(piece)
			yield piece
		self.context.record_narration("".join(parts))

	def _pick_max_tokens(self) -> int:
		# Roughly 3 chars/token for Korean; give headroom over the char budget.
		return max(64, self._max_chars())
