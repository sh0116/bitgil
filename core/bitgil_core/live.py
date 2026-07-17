"""LiveNarrator — F1 live narration loop (screen-reader-agnostic).

Periodically captures a frame, passes it through the change-detection gate, and
— only when the screen changed meaningfully — streams incremental narration to
an output callback, sentence by sentence, for low perceived latency.

Everything is injected (capture, speak, clock) so the loop is fully unit-testable
offline and carries no NVDA dependency. The interruption policy (queue vs. cut
in vs. defer) lives in the caller's `speak` callback — for NVDA that's the
addon's SpeechBridge.
"""

from __future__ import annotations

import threading
from typing import Callable, Iterable, Iterator, List, Optional

from .change_detect import ChangeDetector
from .engine import NarrationEngine

# Characters that close a spoken unit. Includes Korean/CJK and ASCII enders.
_SENTENCE_ENDS = ("。", "！", "？", ".", "!", "?", "\n")


def iter_sentences(chunks: Iterable[str]) -> Iterator[str]:
	"""Aggregate streamed text chunks into whole sentences.

	Provider streams arrive in arbitrary fragments; speaking each fragment makes
	NVDA stutter. This buffers until a sentence boundary, then flushes — so the
	user hears complete phrases as they form. Any trailing text without a
	terminator is flushed at the end.
	"""
	buffer = ""
	for chunk in chunks:
		buffer += chunk
		while True:
			idx = _first_end(buffer)
			if idx == -1:
				break
			sentence = buffer[: idx + 1].strip()
			buffer = buffer[idx + 1 :]
			if sentence:
				yield sentence
	tail = buffer.strip()
	if tail:
		yield tail


def _first_end(text: str) -> int:
	positions = [text.find(e) for e in _SENTENCE_ENDS]
	positions = [p for p in positions if p != -1]
	return min(positions) if positions else -1


class LiveNarrator:
	def __init__(
		self,
		engine: NarrationEngine,
		detector: ChangeDetector,
		capture: Callable[[], bytes],
		speak: Callable[[str], None],
		*,
		interval: float = 1.0,
		on_error: Optional[Callable[[Exception], None]] = None,
	):
		self.engine = engine
		self.detector = detector
		self.capture = capture
		self.speak = speak
		self.interval = interval
		self.on_error = on_error
		self._stop = threading.Event()

	def poll(self) -> Optional[str]:
		"""Run one cycle. Returns the narration spoken, or None if unchanged."""
		frame = self.capture()
		if not self.detector.evaluate(frame).changed:
			return None
		spoken: List[str] = []
		for sentence in iter_sentences(self.engine.narrate_stream(frame)):
			self.speak(sentence)
			spoken.append(sentence)
		return " ".join(spoken) if spoken else None

	def run(self) -> None:
		"""Loop until stop() is called. Meant to run on a background thread."""
		self._stop.clear()
		while not self._stop.is_set():
			try:
				self.poll()
			except Exception as e:  # a bad frame/call must not kill the loop
				if self.on_error is not None:
					self.on_error(e)
			self._stop.wait(self.interval)

	def stop(self) -> None:
		self._stop.set()

	@property
	def running(self) -> bool:
		return not self._stop.is_set()
