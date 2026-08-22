"""Grounding — turn "that button" into a concrete, identified target.

The guidance-first copilot (docs/agent-copilot.md §D) must point at real screen
elements, never invent them (Epic A anti-fabrication). Grounding is deliberately
*tree-first*:

  - The accessibility tree (UIA / AX / DOM) gives labelled, addressable nodes:
    exact, fast, zero vision tokens. A target grounded in the tree is the ONLY
    kind the action gate will let an automator act on.
  - When the tree is too thin, vision can still say "roughly top-right" to guide a
    human — but a vision-only target is GUIDANCE-ONLY. Coordinate jitter makes it
    unfit as the basis for an unattended click, so gate_action() rejects it.

Platform adapters (browser DOM, Windows UIA) populate `Node`s; this module stays
screen-reader- and OS-agnostic and offline-testable, like the rest of the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# Where a target's location came from. Only TREE is trustworthy enough to
# automate on; VISION is for spoken direction to a human.
TREE = "tree"
VISION = "vision"


@dataclass
class Node:
	"""One element from the accessibility tree, as a platform adapter sees it."""

	role: str = ""          # button | link | textbox | checkbox | ...
	name: str = ""          # accessible name / label the user would hear
	node_id: str = ""       # adapter-specific handle the automator can act on
	enabled: bool = True
	focusable: bool = False


@dataclass
class Target:
	"""A grounded target for guidance and (only if source==TREE) automation."""

	label: str = ""
	source: str = VISION        # TREE | VISION
	node: Optional[Node] = None
	confidence: float = 0.0
	hint: str = ""              # human-facing direction, e.g. "화면 우측 상단"

	@property
	def tree_identified(self) -> bool:
		"""True only when a labelled accessibility node backs this target."""
		return self.source == TREE and self.node is not None


def _norm(s: str) -> str:
	return " ".join(s.split()).casefold()


def ground(
	query: str,
	nodes: Optional[List[Node]] = None,
	*,
	vision_hint: str = "",
) -> Optional[Target]:
	"""Resolve `query` (what the user/advisor named) to a Target.

	Tree first: match against node names (exact, then substring). If nothing in the
	tree matches, fall back to a vision hint as GUIDANCE ONLY (source=VISION) so the
	copilot can still say where to look — but the action gate won't automate it.
	Returns None when there's nothing to point at at all.
	"""
	q = _norm(query)
	nodes = nodes or []

	# Exact accessible-name match wins.
	for n in nodes:
		if n.name and _norm(n.name) == q:
			return Target(label=n.name, source=TREE, node=n, confidence=1.0)
	# Then a substring match (query contained in a node name or vice versa).
	for n in nodes:
		nn = _norm(n.name)
		if nn and q and (q in nn or nn in q):
			return Target(label=n.name, source=TREE, node=n, confidence=0.7)

	# No tree match — vision can only guide a human, never ground an auto-click.
	if vision_hint:
		return Target(label=query, source=VISION, confidence=0.3, hint=vision_hint)
	return None
