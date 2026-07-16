# NVDA-specific output layer (GPLv2).
# This is the one place tied to NVDA — it bridges core narration text to the
# screen reader's voice and enforces the interruption policy so EyeMate does not
# talk over the user's own navigation.

from __future__ import annotations


class SpeechBridge:
	"""Speak narration through NVDA, respecting an interruption policy.

	Interruption policy (F1): during a game, EyeMate's narration must not stomp
	on the speech the user triggers by their own actions. Modes:
	  - "queue":     append after current speech (safest, may lag)
	  - "interrupt": cut in immediately (for urgent/important narration)
	  - "defer":     drop if the user is actively navigating
	"""

	def __init__(self, policy: str = "queue"):
		self.policy = policy

	def speak(self, text: str, *, important: bool = False) -> None:
		# TODO(M2): use speech.speakMessage / cancelSpeech per policy + importance.
		import speech  # noqa: F401  (NVDA runtime import)
		raise NotImplementedError("speech bridge lands in M2")
