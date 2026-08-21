"""Tests for the NVDA-independent core logic.

These run in a plain Python environment (no NVDA, no network).
"""

from pathlib import Path

import pytest

from bitgil_core.postprocess import apply_glossary, cap_length
from bitgil_core.profiles import Profile, load_builtin_profiles

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


def test_apply_glossary_longest_key_first():
	# "HP" and "HP bar" should not partially collide; longest first wins.
	text = "HP bar shows HP"
	out = apply_glossary(text, {"HP": "체력", "HP bar": "체력바"})
	assert out == "체력바 shows 체력"


def test_apply_glossary_does_not_rescan_substitutions():
	# Regression: a naive per-term str.replace loop cascaded — the "바" injected by
	# the HP substitution got rewritten again by a later key. A single-pass
	# substitution must leave replacement output untouched.
	out = apply_glossary("HP", {"HP": "체력바", "바": "BAR"})
	assert out == "체력바"


def test_apply_glossary_empty_map_is_noop():
	assert apply_glossary("HP 감소", {}) == "HP 감소"


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


def test_profile_from_yaml_defaults_name_to_filename(tmp_path):
	# A profile that omits `name` must load (addressable by filename stem), not
	# crash on the missing required field.
	p = tmp_path / "myprofile.yaml"
	p.write_text("system_prompt: 안녕\n", encoding="utf-8")
	prof = Profile.from_yaml(p)
	assert prof.name == "myprofile"
	assert prof.system_prompt == "안녕"


def test_profile_from_yaml_rejects_non_mapping(tmp_path):
	p = tmp_path / "bad.yaml"
	p.write_text("- just\n- a\n- list\n", encoding="utf-8")
	with pytest.raises(ValueError):
		Profile.from_yaml(p)


def test_load_builtin_profiles_skips_malformed_file(tmp_path):
	# One broken community pack must not take down the whole directory load.
	(tmp_path / "good.yaml").write_text("name: good\nsystem_prompt: ok\n", encoding="utf-8")
	(tmp_path / "broken.yaml").write_text("name: [unclosed\n", encoding="utf-8")
	(tmp_path / "notmap.yaml").write_text("just a string\n", encoding="utf-8")
	profiles = load_builtin_profiles(tmp_path)
	assert "good" in profiles
	assert "broken" not in profiles and "notmap" not in profiles
