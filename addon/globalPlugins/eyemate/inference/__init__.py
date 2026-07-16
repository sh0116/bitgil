# Inference-layer glue (GPLv2).
# Thin wrapper: reads NVDA config, builds an eyemate_core provider + engine, and
# runs the capture -> change-detect -> narrate flow. All heavy logic lives in
# eyemate_core; this file only wires it to NVDA config/state.

from __future__ import annotations

from eyemate_core.change_detect import ChangeDetector
from eyemate_core.engine import NarrationEngine
from eyemate_core.profiles import Profile
from eyemate_core.providers import build_provider


def build_engine(provider_name: str, provider_config: dict, profile: Profile) -> NarrationEngine:
	"""Construct a NarrationEngine from resolved NVDA config values."""
	provider = build_provider(provider_name, provider_config)
	return NarrationEngine(provider, profile)


def build_change_detector(profile: Profile) -> ChangeDetector:
	# TODO(M2): wire an OCR callable when profile.use_ocr is set.
	return ChangeDetector(hash_threshold=profile.hash_threshold)
