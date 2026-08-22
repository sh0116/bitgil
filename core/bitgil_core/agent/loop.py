"""AdvisorLoop — orchestrate the guidance loop (docs/agent-copilot.md §2, §G).

The state machine's DEFAULT state is "waiting for the user". The agent never
chains its own steps: it advises, the user acts (or explicitly asks for a gated
automation), the screen is re-read and reported, and control returns to the user.

Barge-in is NEW here (§4 notes the draft assumed it existed; it didn't — only
speech cancellation did). `stop()` and an injected `is_stop` predicate both abort
a pending automation *before* it performs, so a user's "멈춰" is honoured even
after an action was requested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .advisor import Advisor, Guidance
from .automator import Action, Automator, GateResult, gate_action
from .grounding import Node
from .intent import IntentSession
from .report import Report, Reporter


@dataclass
class ActResult:
	"""Outcome of a user-initiated automation attempt."""

	performed: bool
	gate: GateResult
	report: Optional[Report] = None
	spoken: str = ""


class AdvisorLoop:
	def __init__(
		self,
		session: IntentSession,
		advisor: Advisor,
		reporter: Reporter,
		automator: Optional[Automator] = None,
		*,
		is_stop: Optional[Callable[[], bool]] = None,
	):
		self.session = session
		self.advisor = advisor
		self.reporter = reporter
		self.automator = automator
		self._is_stop = is_stop
		self._stopped = False

	# --- intent -------------------------------------------------------------
	def set_goal(self, text: str) -> None:
		self.session.set_goal(text)
		self._stopped = False  # a fresh goal clears a prior barge-in

	# --- barge-in -----------------------------------------------------------
	def stop(self) -> None:
		"""User said "멈춰" — abort any pending automation before it runs."""
		self._stopped = True

	def _should_stop(self) -> bool:
		return self._stopped or bool(self._is_stop and self._is_stop())

	# --- advise -------------------------------------------------------------
	def advise(
		self,
		frame: bytes,
		*,
		named_target: str = "",
		nodes: Optional[List[Node]] = None,
	) -> Guidance:
		"""Read the screen and name the next safe step for the current goal."""
		return self.advisor.advise(
			frame, self.session.goal, nodes=nodes, named_target=named_target
		)

	# --- act (user-initiated, gated automation) -----------------------------
	def act(self, action: Action, frame: Optional[bytes] = None) -> ActResult:
		"""Attempt a user-initiated automation: barge-in check → gate → perform → report.

		A denied gate is not a failure — it degrades to spoken guidance (the safe
		default), so the user still gets pointed at the element to do it themselves.
		"""
		if self._should_stop():
			return ActResult(False, GateResult(False, "stopped"), spoken="중단했습니다.")

		result = gate_action(action)
		if not result.allowed:
			# Guidance fallback: never silently drop the user's request.
			return ActResult(
				False, result,
				spoken="이 동작은 자동으로 처리하지 않습니다. 직접 실행하시도록 안내하겠습니다.",
			)

		# Re-check right before performing — barge-in can arrive between gate and act.
		if self._should_stop():
			return ActResult(False, GateResult(False, "stopped"), spoken="중단했습니다.")

		if self.automator is None:
			return ActResult(False, GateResult(False, "no-automator"),
			                 spoken="자동 실행기가 연결되어 있지 않습니다.")

		self.automator.perform(action)
		report = self.reporter.report(frame) if frame is not None else None
		return ActResult(True, result, report=report,
		                 spoken=report.spoken if report else "완료했습니다.")
