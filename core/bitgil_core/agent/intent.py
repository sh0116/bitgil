"""IntentSession — hold the user's spoken goal across a guidance dialogue.

docs/agent-copilot.md §A. A guidance session spans several turns ("로그인하고
싶어" → guide → "눌렀어" → guide next). This keeps the goal and any pending
clarification as one context, layered on the existing GoalTracker.

Critically, it NEVER auto-initiates an action: setting a goal only records intent
and waits for the user's next utterance/keypress. Automation is entered elsewhere
(loop.py), and only on an explicit user-initiated action (see automator.gate_action).
"""

from __future__ import annotations

from typing import Optional

from ..goal import GoalTracker


class IntentSession:
	def __init__(self, tracker: Optional[GoalTracker] = None):
		self._tracker = tracker or GoalTracker()
		self._goal: str = ""
		self._pending_question: str = ""

	@property
	def goal(self) -> str:
		return self._goal

	def set_goal(self, text: str) -> None:
		"""Record a spoken goal. Does not act — waits for the user's next input."""
		text = " ".join(text.split())
		if text:
			self._goal = text
			self._tracker.note(f"목표: {text}")
			self._pending_question = ""

	def note(self, text: str) -> None:
		"""Record an intermediate observation/utterance into the rolling context."""
		self._tracker.note(text)

	def needs_clarification(self, question: str = "") -> bool:
		"""Ambiguous request → ask back rather than guess. `question` sets/queries."""
		if question:
			self._pending_question = " ".join(question.split())
		return bool(self._pending_question)

	@property
	def pending_question(self) -> str:
		return self._pending_question

	def resolve_clarification(self, answer: str) -> None:
		"""User answered the pending question — fold it into the goal."""
		answer = " ".join(answer.split())
		if answer:
			self._goal = (self._goal + " " + answer).strip() if self._goal else answer
			self._tracker.note(answer)
		self._pending_question = ""

	def context(self, max_chars: int = 280) -> str:
		"""Recent activity context (delegates to GoalTracker), for the advisor."""
		return self._tracker.context(max_chars)

	def clear(self) -> None:
		self._goal = ""
		self._pending_question = ""
		self._tracker.clear()
