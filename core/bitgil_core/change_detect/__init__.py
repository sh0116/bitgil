"""Change detection gate.

The whole cost/latency story of Bitgil rests here: we call the vision LLM only
when the screen changes *meaningfully*, not every frame. The gate combines a
cheap perceptual-hash comparison (structural change) with an optional OCR-text
diff (textual change) so we catch both "the picture moved" and "the numbers
changed".
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ChangeResult:
	changed: bool
	# 0.0 (identical) .. 1.0 (completely different) — for tuning thresholds.
	visual_distance: float = 0.0
	text_changed: bool = False
	reason: str = ""


class ChangeDetector:
	"""Decide whether a new frame differs enough to warrant an LLM call.

	Parameters
	----------
	hash_threshold:
		Normalised perceptual-hash distance (0..1) above which a frame counts as
		a visual change. Tune per profile (fast games need a higher bar).
	ocr:
		Optional callable ``bytes -> str`` that extracts on-screen text. When
		provided, a change in its output also triggers narration, so numeric /
		text-only changes (e.g. a health-bar value) are caught even when the
		layout barely moves. Injected rather than imported so the core stays
		free of a hard OCR dependency and stays unit-testable.
	"""

	def __init__(
		self,
		hash_threshold: float = 0.12,
		ocr: Optional[Callable[[bytes], str]] = None,
	):
		self.hash_threshold = hash_threshold
		self.ocr = ocr
		self._last_hash = None
		self._last_text: Optional[str] = None

	def _phash(self, frame: bytes):
		import imagehash
		from PIL import Image

		with Image.open(io.BytesIO(frame)) as img:
			return imagehash.phash(img)

	def evaluate(self, frame: bytes) -> ChangeResult:
		"""Compare ``frame`` (PNG/JPEG bytes) against the previous accepted frame."""
		cur_hash = self._phash(frame)
		if self._last_hash is None:
			distance = 1.0  # first frame is always "new"
		else:
			# phash is 8x8 by default → 64 bits; normalise Hamming distance.
			distance = (cur_hash - self._last_hash) / len(cur_hash.hash) ** 2

		text_changed = False
		cur_text = None
		if self.ocr is not None:
			cur_text = self.ocr(frame)
			text_changed = self._last_text is not None and cur_text != self._last_text

		changed = bool(distance > self.hash_threshold or text_changed)
		if changed:
			self._last_hash = cur_hash
			if cur_text is not None:
				self._last_text = cur_text

		reason = ""
		if changed:
			reason = "text" if (text_changed and distance <= self.hash_threshold) else "visual"

		return ChangeResult(
			changed=changed,
			visual_distance=float(distance),
			text_changed=bool(text_changed),
			reason=reason,
		)
