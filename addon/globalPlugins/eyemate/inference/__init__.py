# Inference-layer glue (GPLv2).
# Thin wrapper: reads NVDA config, builds an eyemate_core provider + engine, and
# runs the capture -> change-detect -> narrate flow. All heavy logic lives in
# eyemate_core; this file only wires it to NVDA config/state.

from __future__ import annotations

from typing import Optional

from eyemate_core.change_detect import ChangeDetector
from eyemate_core.engine import NarrationEngine
from eyemate_core.profiles import Profile
from eyemate_core.providers import build_provider
from eyemate_core.review import ReviewLog


def build_engine(
	provider_name: str,
	provider_config: dict,
	profile: Profile,
	review_log: Optional[ReviewLog] = None,
) -> NarrationEngine:
	"""Construct a NarrationEngine from resolved NVDA config values."""
	provider = build_provider(provider_name, provider_config)
	return NarrationEngine(provider, profile, review_log=review_log)


def build_change_detector(profile: Profile) -> ChangeDetector:
	"""Build the change-detection gate, attaching OCR when the profile asks."""
	ocr = None
	if profile.use_ocr:
		try:
			from eyemate_core.ocr import build_ocr

			ocr = build_ocr()
		except Exception:
			# OCR extra not installed / model unavailable — fall back to the
			# visual-only gate rather than failing to start live mode.
			ocr = None
	return ChangeDetector(hash_threshold=profile.hash_threshold, ocr=ocr)
