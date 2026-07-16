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
		if not text:
			return
		# NVDA runtime imports (only available inside the NVDA process).
		import queueHandler
		import speech

		policy = "interrupt" if important else self.policy

		if policy == "defer" and self._user_speaking():
			return  # user is navigating — stay out of the way

		def _emit():
			if policy == "interrupt":
				speech.cancelSpeech()
			speech.speakMessage(text)

		# Speech must run on NVDA's main thread; the live loop runs on its own
		# thread, so hop back via queueHandler.
		queueHandler.queueFunction(queueHandler.eventQueue, _emit)

	@staticmethod
	def _user_speaking() -> bool:
		"""True if the user seems to be actively navigating (speech in progress).

		TODO(M2): NVDA has no stable public "is currently speaking" query across
		versions. Track it ourselves by observing when we last enqueued speech,
		or hook the synth's index-reached callback. Until then, `defer` behaves
		like `queue` (never drops) — the safe default.
		"""
		return False
