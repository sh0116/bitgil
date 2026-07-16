"""Session context: what the LLM sees besides the current frame.

For incremental narration (F1) the model needs to know what it already said, so
it can describe *what changed* rather than re-describing the whole screen. This
holds the last N narrations plus the active profile's system prompt.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List

from ..providers.base import Message


class SessionContext:
	def __init__(self, system_prompt: str, history_size: int = 5):
		self.system_prompt = system_prompt
		self._history: Deque[str] = deque(maxlen=history_size)

	def record_narration(self, text: str) -> None:
		self._history.append(text)

	def recent(self) -> List[str]:
		return list(self._history)

	def build_messages(self, frame: bytes, user_text: str = "") -> List[Message]:
		"""Assemble the message list for a provider call.

		Includes the profile system prompt, a short recap of recent narrations
		(so the model can speak incrementally), and the current frame.
		"""
		msgs: List[Message] = [Message(role="system", text=self.system_prompt)]
		if self._history:
			recap = "이전 해설(최근순):\n" + "\n".join(f"- {h}" for h in self._history)
			msgs.append(Message(role="system", text=recap))
		msgs.append(Message(role="user", text=user_text, image=frame))
		return msgs
