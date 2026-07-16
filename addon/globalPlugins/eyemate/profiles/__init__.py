# Profile-system glue (GPLv2).
# Locates the profile packs bundled into the add-on and loads them via
# eyemate_core. Community packs from the eyemate-profiles repo drop into the
# same directory. Heavy logic (YAML parsing) lives in eyemate_core.profiles.

from __future__ import annotations

import os
from typing import Dict, List

from eyemate_core.profiles import Profile, load_builtin_profiles

# Built-in fallback so the add-on still works if no packs are bundled.
_FALLBACK = Profile(
	name="general",
	system_prompt="화면을 간결히 설명하세요. 이전 해설이 있으면 무엇이 달라졌는지 중심으로 말하세요.",
)


def packs_dir() -> str:
	"""Directory holding bundled *.yaml profile packs (populated at build time)."""
	here = os.path.dirname(os.path.dirname(__file__))  # .../globalPlugins/eyemate
	return os.path.join(here, "profile_packs")


def _load_all() -> Dict[str, Profile]:
	d = packs_dir()
	if os.path.isdir(d):
		packs = load_builtin_profiles(d)
		if packs:
			return packs
	return {_FALLBACK.name: _FALLBACK}


def available_profile_names() -> List[str]:
	return sorted(_load_all().keys())


def load_profile(name: str) -> Profile:
	return _load_all().get(name, _FALLBACK)
