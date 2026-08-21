"""YAML profile loader.

A profile tailors Bitgil to a specific game or learning platform without code
changes — the structural answer to "game updates break the mod". Community packs
live in a separate repo (bitgil-profiles) and are contributed as YAML, so
non-developers (including blind users themselves) can contribute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml


@dataclass
class Profile:
	name: str
	domain: str = "general"  # general | game-turnbased | game-realtime | learning-* ...
	language: str = "ko"
	system_prompt: str = ""
	glossary: Dict[str, str] = field(default_factory=dict)
	# Regions of interest, e.g. {"health": [x, y, w, h]} as fractions 0..1.
	roi: Dict[str, List[float]] = field(default_factory=dict)
	# Change-detection tuning per profile.
	hash_threshold: float = 0.12
	use_ocr: bool = False
	narration_density: str = "normal"  # brief | normal | detailed
	# Seconds between live-mode observations. Lecture videos want a longer
	# interval (only slide flips matter); real-time games want a shorter one.
	observe_interval: float = 1.5
	# Latency vs. quality preference, resolved to a concrete model per provider
	# (see VisionProvider.model_for_speed). Profiles stay provider-agnostic — a
	# game profile asks for "fast", not "claude-haiku". LLM round-trip dominates
	# live-mode latency, so this is the biggest lever a profile has over it.
	speed: str = "balanced"  # quality | balanced | fast
	# Longest image edge (px) sent to the model; 0 = send as captured. Downscaling
	# cuts upload size and vision-token count — both latency and cost — with little
	# quality loss for on-screen text/UI. Fast profiles set this low.
	max_image_dim: int = 0

	@classmethod
	def from_yaml(cls, path: str | Path) -> "Profile":
		path = Path(path)
		data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
		if not isinstance(data, dict):
			raise ValueError(f"profile {path} is not a YAML mapping")
		known = {f for f in cls.__dataclass_fields__}
		kwargs = {k: v for k, v in data.items() if k in known}
		# `name` is the only required field; default it to the filename stem so a
		# profile that omits it loads (and stays addressable) instead of crashing.
		kwargs.setdefault("name", path.stem)
		return cls(**kwargs)


def load_builtin_profiles(directory: str | Path) -> Dict[str, Profile]:
	"""Load every *.yaml under `directory` into a name -> Profile map.

	A single malformed file (bad YAML, wrong shape) is skipped rather than
	aborting the whole load — one broken community pack must not take down every
	other profile. Skips are reported to stderr for debugging.
	"""
	out: Dict[str, Profile] = {}
	for p in sorted(Path(directory).glob("*.yaml")):
		try:
			prof = Profile.from_yaml(p)
		except (yaml.YAMLError, ValueError, TypeError) as exc:
			import sys
			print(f"bitgil: skipping malformed profile {p}: {exc}", file=sys.stderr)
			continue
		out[prof.name] = prof
	return out
