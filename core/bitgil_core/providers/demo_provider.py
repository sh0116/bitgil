"""Keyless demo provider — runs the whole pipeline with zero credentials.

Not a real vision model: it returns canned Korean narration that rotates each
call, so the capture -> change-detect -> narrate -> speak loop (and streaming, the
review transcript, triage's heuristic fallback) is observable on any machine —
including a Raspberry Pi — without an API key. Selected with provider name
``demo`` (CLI ``--provider demo`` or the web backend's default).

Because it never emits JSON, routing a triage call through it also exercises the
deterministic safety fallback path (bitgil_core.safety), which is exactly what
the offline QA in docs/qa.md relies on.
"""

from __future__ import annotations

import itertools
from typing import Iterator, Sequence

from .base import Message, VisionProvider, VisionResponse

_LINES = (
	"화면 상단에 제목 표시줄이 보입니다.",
	"가운데에 본문 텍스트가 바뀌었습니다.",
	"오른쪽 아래에 알림이 하나 나타났습니다.",
	"버튼 두 개가 새로 생겼습니다: 확인, 취소.",
	"진행 표시줄이 절반쯤 찼습니다.",
)


class DemoProvider(VisionProvider):
	name = "demo"

	def __init__(self) -> None:
		# Rotates so successive calls differ — makes streaming / interruption /
		# the review transcript observable without a real model.
		self._i = itertools.count()

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		line = _LINES[next(self._i) % len(_LINES)]
		return VisionResponse(text="(데모) " + line)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		yield self.complete(messages).text
