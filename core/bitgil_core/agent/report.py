"""Reporter — transparently tell the user what changed (replaces draft "verifier").

docs/agent-copilot.md §E. The draft had a verifier that silently judged
success/failure and auto-replanned. For a user who can't see the screen, hidden
retries hide errors. So this is reframed as *reporting*: after the user acts (or a
gated automation runs), detect that the screen changed and say what now appears —
then hand judgement back to the user.

Reuses the existing ChangeDetector (change trigger) and NarrationEngine (spoken
description). Injected, so offline-testable with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..change_detect import ChangeDetector
from ..engine import NarrationEngine


@dataclass
class Report:
	changed: bool
	spoken: str
	reason: str = ""


class Reporter:
	def __init__(self, engine: NarrationEngine, detector: Optional[ChangeDetector] = None):
		self.engine = engine
		self.detector = detector or ChangeDetector()

	def report(self, frame: bytes) -> Report:
		"""Describe what now appears if the screen changed; else say nothing new.

		Never accumulates silent retries — a no-change frame reports honestly that
		nothing visibly changed, leaving the next move to the user.
		"""
		result = self.detector.evaluate(frame)
		if not result.changed:
			return Report(False, "화면에 눈에 띄는 변화가 없습니다.", reason="no-change")
		text = self.engine.narrate(frame).text
		return Report(True, text, reason=result.reason)
