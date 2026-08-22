"""Advisor — "so what's the next safe step?" (replaces the draft's planner).

docs/agent-copilot.md §B. Given the user's goal and the current screen, the
advisor names ONE next action — its label, where it is, and the keyboard path to
reach it — instead of decomposing a multi-step plan to auto-execute. The user does
that one thing, the screen is re-read, and the next step is advised.

Two hard rules, straight from Epic A (anti-fabrication) and §F (safety):
  - Point only at elements actually on screen; never invent a button.
  - For irreversible/security targets (pay/delete/install/login/submit/send),
    warn about the consequence FIRST — the user can't see it coming.

Takes an injected VisionProvider, so it's offline-testable with a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..providers.base import Message, VisionProvider
from .grounding import Node, Target, ground

_GUIDANCE_SYSTEM = """당신은 화면을 볼 수 없는 사용자를 이끄는 안내자입니다. 사용자를 대신해
조작하지 않습니다. 사용자의 목표와 현재 화면을 보고, **지금 할 안전한 한 가지**만 알려주세요.

규칙:
- 화면에 실제로 보이는 요소만 지목하세요. 없는 버튼·메뉴를 지어내지 마세요.
- 그 요소의 이름, 화면상 위치, 키보드로 가는 경로(예: Tab 3번 후 Enter)를 함께 말하세요.
- 결제·삭제·설치·로그인·전송처럼 되돌릴 수 없는 행동이면, 무슨 결과가 생기는지 **먼저 경고**하세요.
- 확실하지 않으면 "확실하지 않습니다"라고 말하고 짐작하지 마세요.
- 실행 키는 사용자가 직접 누릅니다. 명령하지 말고 안내하세요.
간결한 한국어 한두 문장으로 답하세요."""


@dataclass
class Guidance:
	"""One step of spoken guidance, optionally with a grounded target."""

	text: str
	target: Optional[Target] = None


class Advisor:
	def __init__(self, provider: VisionProvider, max_tokens: int = 200):
		self.provider = provider
		self.max_tokens = max_tokens

	def advise(
		self,
		frame: bytes,
		goal: str,
		*,
		nodes: Optional[List[Node]] = None,
		named_target: str = "",
	) -> Guidance:
		"""Produce next-step guidance for `goal` given the current `frame`.

		If `named_target` is given, try to ground it in `nodes` (tree-first) so the
		returned Guidance carries a concrete Target for a possible user-initiated,
		gated automation step downstream.
		"""
		messages = [
			Message(role="system", text=_GUIDANCE_SYSTEM),
			Message(role="user", text=f"사용자의 목표: {goal}", image=frame),
		]
		resp = self.provider.complete(messages, max_tokens=self.max_tokens)
		target = ground(named_target, nodes) if named_target else None
		return Guidance(text=resp.text.strip(), target=target)
