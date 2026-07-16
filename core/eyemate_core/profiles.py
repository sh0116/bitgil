"""YAML profile loader.

A profile tailors EyeMate to a specific game or learning platform without code
changes — the structural answer to "game updates break the mod". Community packs
live in a separate repo (eyemate-profiles) and are contributed as YAML, so
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

	@classmethod
	def from_yaml(cls, path: str | Path) -> "Profile":
		data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
		known = {f for f in cls.__dataclass_fields__}
		return cls(**{k: v for k, v in data.items() if k in known})


def load_builtin_profiles(directory: str | Path) -> Dict[str, Profile]:
	"""Load every *.yaml under `directory` into a name -> Profile map."""
	out: Dict[str, Profile] = {}
	for p in sorted(Path(directory).glob("*.yaml")):
		prof = Profile.from_yaml(p)
		out[prof.name] = prof
	return out
