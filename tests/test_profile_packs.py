"""End-to-end check of the real profile packs through the engine.

Exercises the exact path the CLI demo and the NVDA add-on use: load a bundled
YAML pack, run it through NarrationEngine with a fake provider (offline).
"""

import io
from pathlib import Path

from PIL import Image

from bitgil_core.engine import NarrationEngine
from bitgil_core.profiles import load_builtin_profiles
from bitgil_core.providers.base import VisionProvider, VisionResponse

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


class EchoProvider(VisionProvider):
	name = "echo"

	def __init__(self, reply):
		self.reply = reply

	def complete(self, messages, *, max_tokens=300):
		return VisionResponse(text=self.reply)

	def stream(self, messages, *, max_tokens=300):
		yield self.reply


def _png() -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", (16, 16), "white").save(buf, format="PNG")
	return buf.getvalue()


def test_turnbased_pack_glossary_flows_through_engine():
	profile = load_builtin_profiles(PROFILES_DIR)["game-turnbased"]
	# The pack maps HP -> 체력; narration should come out substituted.
	engine = NarrationEngine(EchoProvider("HP 감소"), profile)
	assert engine.narrate(_png()).text == "체력 감소"


def test_lecture_pack_has_long_observe_interval():
	profile = load_builtin_profiles(PROFILES_DIR)["learning-lecture"]
	assert profile.observe_interval == 3.0  # slides change slowly


def test_chart_pack_is_detailed_density():
	profile = load_builtin_profiles(PROFILES_DIR)["learning-chart"]
	assert profile.narration_density == "detailed"
