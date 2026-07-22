"""Offline coverage for the NVDA add-on layer — no NVDA, no Windows.

NVDA can't run on Linux/CI, but most of the add-on's logic is plain Python. We
load the NVDA-coupled modules by file path (bypassing the package __init__ that
imports globalPluginHandler) and feed them fake NVDA runtime modules, so the
SpeechBridge interruption policy and the inference glue get real assertions.
"""

import importlib.util
import os
import sys
import types

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADDON = os.path.join(_REPO, "addon", "globalPlugins", "bitgil")


def _load(name: str, relpath: str):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_ADDON, relpath))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


# --- SpeechBridge (output layer): the NVDA interruption policy ---------------

def _install_fake_nvda_speech():
	"""Fake `speech` + `queueHandler` so SpeechBridge.speak() runs synchronously."""
	calls = []
	speech = types.ModuleType("speech")
	speech.cancelSpeech = lambda: calls.append("cancel")
	speech.speakMessage = lambda m: calls.append(("speak", m))
	qh = types.ModuleType("queueHandler")
	qh.eventQueue = object()
	qh.queueFunction = lambda q, fn, *a, **k: fn()  # run inline for the test
	sys.modules["speech"] = speech
	sys.modules["queueHandler"] = qh
	return calls


_output = _load("bitgil_output", os.path.join("output", "__init__.py"))
SpeechBridge = _output.SpeechBridge


def test_queue_policy_speaks_without_cancel():
	calls = _install_fake_nvda_speech()
	SpeechBridge(policy="queue").speak("안녕")
	assert calls == [("speak", "안녕")]


def test_interrupt_policy_cancels_then_speaks():
	calls = _install_fake_nvda_speech()
	SpeechBridge(policy="interrupt").speak("급함")
	assert calls == ["cancel", ("speak", "급함")]


def test_important_flag_forces_interrupt():
	calls = _install_fake_nvda_speech()
	SpeechBridge(policy="queue").speak("경고", important=True)
	assert calls == ["cancel", ("speak", "경고")]


def test_empty_text_says_nothing():
	calls = _install_fake_nvda_speech()
	SpeechBridge().speak("")
	assert calls == []


# --- inference glue: builds core objects from resolved config ----------------

_inference = _load("bitgil_inference", os.path.join("inference", "__init__.py"))


def test_build_engine_returns_narration_engine():
	from bitgil_core.engine import NarrationEngine
	from bitgil_core.profiles import Profile

	engine = _inference.build_engine("bedrock", {}, Profile(name="t", system_prompt="s"))
	assert isinstance(engine, NarrationEngine)


def test_build_change_detector_without_ocr():
	from bitgil_core.change_detect import ChangeDetector
	from bitgil_core.profiles import Profile

	det = _inference.build_change_detector(Profile(name="t", use_ocr=False, hash_threshold=0.2))
	assert isinstance(det, ChangeDetector)
	assert det.hash_threshold == 0.2
	assert det.ocr is None
