"""Change detection gate.

The whole cost/latency story of EyeMate rests here: we call the vision LLM only
when the screen changes *meaningfully*, not every frame. The gate combines a
cheap perceptual-hash comparison (structural change) with an optional OCR-text
diff (textual change) so we catch both "the picture moved" and "the numbers
changed".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
		Normalised perceptual-hash distance above which a frame counts as a
		visual change. Tune per profile (fast games need a higher bar).
	use_ocr:
		When True, also diff OCR text so numeric/text-only changes (e.g. a health
		bar value) trigger narration even if the layout barely moves.
	"""

	def __init__(self, hash_threshold: float = 0.12, use_ocr: bool = False):
		self.hash_threshold = hash_threshold
		self.use_ocr = use_ocr
		self._last_hash = None
		self._last_text: Optional[str] = None

	def evaluate(self, frame: bytes) -> ChangeResult:
		"""Compare `frame` (PNG/JPEG bytes) against the previous accepted frame."""
		# TODO(M2): imagehash.phash on the decoded image; compare to self._last_hash.
		# TODO(M2): optional OCR diff when self.use_ocr.
		raise NotImplementedError("change detection lands in M2")
