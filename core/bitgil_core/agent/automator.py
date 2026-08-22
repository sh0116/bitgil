"""Action gate + automator interface — the safety centerpiece of the copilot.

docs/agent-copilot.md §C/§F, corrected §4: the draft claimed `safety.apply_policy`
was an outgoing-action gate. It is not — `triage.apply_policy` classifies *incoming*
desktop events and cannot block an action. So the gate on *outgoing* actions is NEW
and lives here.

`gate_action()` is a pure, deterministic function (no LLM, no I/O) so the whole
allow/deny policy is exhaustively unit-testable without a model or a real desktop.
It DEFAULT-DENIES: automation is permitted only when ALL three hold —

  1. the user explicitly initiated this one action (not agent-chained),
  2. the action is reversible (read-only navigation: scroll / focus / read), and
  3. the target is identified in the accessibility tree (a labelled node), never
     from vision coordinates alone.

Anything touching money / deletion / installation / login / submission / sending /
a security prompt is NEVER automated — the copilot guides instead. When the gate
denies, the caller falls back to spoken guidance (the safe default), so a denial
degrades gracefully rather than dropping the user's request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .grounding import Target

# Reversible, read-only action kinds — the ONLY kinds eligible for automation.
# Everything else (activate/click, input, submit, ...) is guidance-only for now;
# the roadmap widens this only after user-testing proves it safe (M7-c).
REVERSIBLE_KINDS = frozenset({"scroll", "focus", "read", "navigate_readonly"})

# Verbs/labels that mark an irreversible or security-sensitive action. If a
# target's label matches any of these, the action is guidance-only even if its
# kind looks reversible — a "scroll" onto a labelled "결제" control is a red flag.
_SENSITIVE_SIGNALS = (
	# Korean
	"결제", "구매", "삭제", "지우", "설치", "로그인", "가입", "전송", "보내기",
	"제출", "확인", "동의", "허용", "권한", "비밀번호", "카드", "송금", "이체",
	# English
	"pay", "purchase", "buy", "checkout", "delete", "remove", "uninstall",
	"install", "login", "log in", "sign in", "sign up", "submit", "send",
	"transfer", "confirm", "allow", "grant", "permission", "password",
)


@dataclass
class Action:
	"""A proposed outgoing action. `user_initiated` must be set by the caller
	from a real user utterance/keypress — never inferred by the agent itself."""

	kind: str = ""                       # scroll | focus | read | activate | input | ...
	target: Optional[Target] = None
	user_initiated: bool = False
	description: str = ""                 # human-facing, for the pre-action announce


@dataclass
class GateResult:
	allowed: bool
	reason: str
	fallback: str = "guidance"           # what to do instead when denied


def _looks_sensitive(text: str) -> bool:
	low = text.casefold()
	return any(sig in low for sig in _SENSITIVE_SIGNALS)


def gate_action(action: Action) -> GateResult:
	"""Decide whether `action` may be automated. Pure and default-deny.

	Every denial names why and routes to spoken guidance, which is always safe:
	the user still gets pointed at the element and presses the key themselves.
	"""
	# 1. Must be user-initiated. The agent never chains its own actions.
	if not action.user_initiated:
		return GateResult(False, "not-user-initiated")

	# 2. Must be a reversible, read-only kind.
	if action.kind not in REVERSIBLE_KINDS:
		return GateResult(False, f"irreversible-kind:{action.kind or 'unknown'}")

	# 3. Must be grounded in the accessibility tree (labelled node), not vision.
	target = action.target
	if target is None or not target.tree_identified:
		return GateResult(False, "not-tree-identified")

	# 4. Even a reversible kind on a sensitive target (pay/delete/login/security)
	#    is guidance-only — check both the target label and the description.
	if _looks_sensitive(target.label) or _looks_sensitive(action.description):
		return GateResult(False, "sensitive-target")

	return GateResult(True, "ok", fallback="")


class Automator:
	"""Abstract adapter that performs a *gated* action on a concrete platform.

	Concrete adapters (browser DOM, Windows UIA) implement `perform` for the narrow
	reversible set only. Callers must run `gate_action()` first; `run()` enforces
	that so an adapter can never be driven around the gate.
	"""

	def perform(self, action: Action) -> None:  # pragma: no cover - abstract
		raise NotImplementedError

	def run(self, action: Action) -> GateResult:
		"""Gate, then perform only if allowed. Returns the gate decision."""
		result = gate_action(action)
		if result.allowed:
			self.perform(action)
		return result
