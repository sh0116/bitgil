"""Tests for the NVDA-independent core logic.

These run in a plain Python environment (no NVDA, no network).
"""

from pathlib import Path

import pytest

from eyemate_core.postprocess import apply_glossary, cap_length
from eyemate_core.profiles import Profile, load_builtin_profiles

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


def test_apply_glossary_longest_key_first():
	# "HP" and "HP bar" should not partially collide; longest first wins.
	text = "HP bar shows HP"
	out = apply_glossary(text, {"HP": "체력", "HP bar": "체력바"})
	assert out == "체력바 shows 체력"


def test_cap_length_breaks_on_sentence_boundary():
	text = "첫 문장입니다. 두 번째 문장은 잘려야 합니다."
	out = cap_length(text, 12)
	assert out == "첫 문장입니다."


def test_cap_length_noop_when_short():
	assert cap_length("짧음", 100) == "짧음"


@pytest.mark.parametrize(
	"name",
	[
		"general",
		"game-turnbased",
		"game-realtime",
		"learning-lecture",
		"learning-chart",
		"learning-math",
	],
)
def test_builtin_profile_loads(name):
	profiles = load_builtin_profiles(PROFILES_DIR)
	assert name in profiles
	prof = profiles[name]
	assert isinstance(prof, Profile)
	assert prof.system_prompt.strip(), f"{name} must have a system prompt"


def test_builtin_profile_count():
	# The plan promises 6 built-in profiles at launch.
	assert len(load_builtin_profiles(PROFILES_DIR)) == 6
