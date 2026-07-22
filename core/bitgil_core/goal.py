"""GoalTracker — a lightweight rolling model of what the user is doing.

The interruption triage (bitgil_core.triage) judges whether an event is
*relevant to the user's current goal*. But "goal" is fuzzy and expensive to infer
perfectly, so this keeps it deliberately simple and deterministic: a bounded
window of recent activity (narrations / events) that can be handed to the triage
as context. No LLM, no dependency — offline-testable like the rest of the core.

A fuller version could periodically summarise the window into a one-line goal via
the LLM; the interface (`context()`) is designed so that swap stays local.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List


class GoalTracker:
	def __init__(self, window: int = 8):
		self._obs: Deque[str] = deque(maxlen=window)

	def note(self, text: str) -> None:
		"""Record an observation (a narration or event summary)."""
		if text and text.strip():
			self._obs.append(text.strip())

	def observations(self) -> List[str]:
		return list(self._obs)

	def context(self, max_chars: int = 280) -> str:
		"""Recent activity, most-recent first, as a compact context string.

		Suitable to pass as the triage `user_goal` when the caller has no explicit
		goal — it lets the model judge relevance against what just happened.
		"""
		joined = " / ".join(reversed(self._obs))
		return joined[:max_chars]

	def clear(self) -> None:
		self._obs.clear()
