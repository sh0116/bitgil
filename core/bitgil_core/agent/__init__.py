"""Guidance-first copilot scaffold (M7-a).

The human is the actor; the AI is the eyes and the guide. See docs/agent-copilot.md.
Everything here is platform-agnostic and offline-testable — concrete platform
adapters (browser DOM, Windows UIA) live outside the core and implement only the
narrow reversible action set the gate permits.

The safety centerpiece is `gate_action` (automator.py): a pure, default-deny gate
on OUTGOING actions — distinct from `triage.apply_policy`, which classifies
INCOMING events and cannot block an action.
"""

from .advisor import Advisor, Guidance
from .automator import Action, Automator, GateResult, gate_action
from .grounding import Node, Target, ground
from .intent import IntentSession
from .loop import ActResult, AdvisorLoop
from .report import Report, Reporter

__all__ = [
	"Advisor",
	"Guidance",
	"Action",
	"Automator",
	"GateResult",
	"gate_action",
	"Node",
	"Target",
	"ground",
	"IntentSession",
	"ActResult",
	"AdvisorLoop",
	"Report",
	"Reporter",
]
