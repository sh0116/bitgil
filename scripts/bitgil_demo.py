#!/usr/bin/env python3
"""Bitgil CLI prototype — narrate a screenshot without NVDA.

Runs the exact core pipeline (profile -> provider -> engine) the add-on uses, so
you can see and tune narration quality on any machine, with your own API key or
a local Ollama, before installing into NVDA.

Examples
--------
  # Describe an image with Anthropic (reads ANTHROPIC_API_KEY from env)
  python scripts/bitgil_demo.py --image slide.png --provider anthropic

  # Local, private, offline — needs a running Ollama with a vision model
  python scripts/bitgil_demo.py --image board.png --provider ollama --model llava

  # Capture the current screen and ask a question (desktop only)
  python scripts/bitgil_demo.py --screen --ask "내 체력이 얼마야?"

  # Use a learning profile and stream the narration
  python scripts/bitgil_demo.py --image chart.png --profile learning-chart --stream
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Allow running from a checkout without installing bitgil-core.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "core"))

from bitgil_core.engine import NarrationEngine  # noqa: E402
from bitgil_core.profiles import Profile, load_builtin_profiles  # noqa: E402
from bitgil_core.providers import build_provider  # noqa: E402
from bitgil_core.review import ReviewLog  # noqa: E402

DEFAULT_PROFILES_DIR = os.path.join(_REPO, "profiles")


def _load_frame(args) -> bytes:
	if args.screen:
		from bitgil_core.capture import capture_screen

		return capture_screen()
	if not args.image:
		sys.exit("error: pass --image <path> or --screen")
	with open(args.image, "rb") as f:
		return f.read()


def _load_profile(name: str, directory: str) -> Profile:
	if os.path.isdir(directory):
		packs = load_builtin_profiles(directory)
		if name in packs:
			return packs[name]
	if name == "general":
		return Profile(name="general", system_prompt="화면을 간결히 설명하세요.")
	sys.exit(f"error: profile '{name}' not found in {directory}")


def main() -> None:
	p = argparse.ArgumentParser(description="Bitgil CLI prototype")
	src = p.add_mutually_exclusive_group()
	src.add_argument("--image", help="path to a screenshot (PNG/JPEG)")
	src.add_argument("--screen", action="store_true", help="capture the current screen")
	p.add_argument("--provider", default="ollama", help="ollama | anthropic | openai")
	p.add_argument("--model", help="override the provider's default model")
	p.add_argument("--api-key", help="API key (else read from provider's env var)")
	p.add_argument("--profile", default="general", help="profile pack name")
	p.add_argument("--profiles-dir", default=DEFAULT_PROFILES_DIR)
	p.add_argument("--ask", default="", help="question about the screen (F2); blank = describe")
	p.add_argument("--stream", action="store_true", help="stream narration as it arrives")
	args = p.parse_args()

	frame = _load_frame(args)
	profile = _load_profile(args.profile, args.profiles_dir)

	provider_config = {}
	if args.api_key:
		provider_config["api_key"] = args.api_key
	if args.model:
		provider_config["model"] = args.model
	# --model (if given) wins; otherwise the profile's speed tier picks the model.
	provider = build_provider(args.provider, provider_config, speed=profile.speed)

	model = getattr(provider, "model", "?")
	review = ReviewLog(
		clock=lambda: time.strftime("%H:%M:%S"),
		provider=provider.name,
		model=model,
	)
	engine = NarrationEngine(provider, profile, review_log=review)

	print(
		f"[profile={profile.name} provider={provider.name} model={model} "
		f"speed={profile.speed} density={profile.narration_density}]"
	)
	started = time.monotonic()
	try:
		if args.stream:
			for chunk in engine.narrate_stream(frame, question=args.ask):
				print(chunk, end="", flush=True)
			print()
		else:
			out = engine.narrate(frame, question=args.ask)
			print(out.text)
			print(
				f"\n[tokens in={out.prompt_tokens} out={out.completion_tokens} "
				f"latency={time.monotonic() - started:.2f}s]"
			)
	except Exception as e:
		sys.exit(
			f"provider call failed: {e}\n"
			f"(check the API key / that Ollama is running with a vision model)"
		)


if __name__ == "__main__":
	main()
