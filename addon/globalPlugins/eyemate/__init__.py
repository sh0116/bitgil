# EyeMate (눈동무) — NVDA global plugin entry point
# Copyright (C) 2026 EyeMate contributors
# Licensed under GPLv2 (see repository root LICENSE).
#
# This module wires EyeMate into NVDA. It is intentionally thin: all reusable
# logic (providers, change detection, context, post-processing) lives in the
# MIT-licensed `eyemate_core` package so it can be reused by other screen
# readers or standalone apps. This plugin only handles NVDA integration:
# gestures, speech output, and lifecycle.

import globalPluginHandler
from scriptHandler import script

# NOTE: `eyemate_core` is bundled into the add-on at build time. During NVDA
# runtime the import path is set up by the add-on packager. See
# docs/development.md for the build story.


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""EyeMate NVDA integration.

	Responsibilities:
	  - Register keyboard gestures for the core features (F1 live mode, F2 ask).
	  - Bridge core narration output to NVDA's speech API.
	  - Manage the live-narration session lifecycle.

	Design principle: EyeMate augments NVDA rather than replacing it. Where the
	screen is accessible, NVDA handles it; EyeMate fills the visual blind spots.
	"""

	scriptCategory = "EyeMate"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._engine = None  # lazily built on first use
		self._profile = None
		self._narrator = None  # active LiveNarrator, if live mode is on
		self._live_thread = None
		self._speech = None

	def terminate(self, *args, **kwargs):
		self._stop_live()
		super().terminate(*args, **kwargs)

	def _get_engine_and_profile(self):
		"""Build the NarrationEngine + its profile on demand from configuration.

		TODO(M3): read provider name / API key / active profile from the NVDA
		settings panel. For now this uses eyemate_core defaults so the
		capture -> LLM -> speech path can be exercised end to end.
		"""
		if self._engine is None:
			from eyemate_core.profiles import Profile
			from .inference import build_engine

			# Placeholder config until the settings panel lands (M3).
			self._profile = Profile(
				name="general",
				system_prompt="화면을 간결히 설명하세요. 이전 해설이 있으면 무엇이 달라졌는지 중심으로 말하세요.",
			)
			self._engine = build_engine("ollama", {}, self._profile)
		return self._engine, self._profile

	# --- F1: Live Narrator ------------------------------------------------

	@script(
		description="Toggle EyeMate live screen narration",
		gesture="kb:NVDA+shift+e",
	)
	def script_toggleLiveNarration(self, gesture):
		import ui

		if self._narrator is not None:
			self._stop_live()
			ui.message("EyeMate: 라이브 해설 종료")
			return

		try:
			import threading

			from eyemate_core.capture import capture_screen
			from eyemate_core.live import LiveNarrator

			from .inference import build_change_detector
			from .output import SpeechBridge

			# TODO(M3): read profile/provider/interval from the settings panel.
			engine, profile = self._get_engine_and_profile()
			self._speech = SpeechBridge(policy="queue")
			self._narrator = LiveNarrator(
				engine=engine,
				detector=build_change_detector(profile),
				capture=capture_screen,
				speak=self._speech.speak,
				interval=1.5,
				on_error=lambda e: ui.message(f"EyeMate 오류: {e}"),
			)
			self._live_thread = threading.Thread(target=self._narrator.run, daemon=True)
			self._live_thread.start()
			ui.message("EyeMate: 라이브 해설 시작")
		except Exception as e:
			self._narrator = None
			ui.message(f"EyeMate 오류: {e}")

	def _stop_live(self):
		if self._narrator is not None:
			self._narrator.stop()
			self._narrator = None
			self._live_thread = None

	# --- F2: Ask the Screen ----------------------------------------------

	@script(
		description="Ask EyeMate a question about the current screen",
		gesture="kb:NVDA+shift+a",
	)
	def script_askScreen(self, gesture):
		# M1 one-shot flow: capture the screen, narrate it, speak the result.
		# Runs off the main thread so a slow LLM call never freezes NVDA.
		import threading

		import ui

		def worker():
			try:
				from eyemate_core.capture import capture_screen

				frame = capture_screen()
				engine, _ = self._get_engine_and_profile()
				narration = engine.narrate(frame)
				ui.message(narration.text)
			except Exception as e:  # surface failures as speech, never crash NVDA
				ui.message(f"EyeMate 오류: {e}")

		ui.message("EyeMate: 화면을 확인하는 중...")
		threading.Thread(target=worker, daemon=True).start()
