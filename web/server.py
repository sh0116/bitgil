#!/usr/bin/env python3
"""Bitgil web backend — a thin FrameSource/SpeechSink adapter over bitgil_core.

This is the "screen is just a screen" reference server (see docs/ambient-copilot.md
and docs/architecture.md). The browser captures any device's screen via
getDisplayMedia and speaks via the Web Speech API; this server does the heavy
lifting by reusing the EXACT platform-agnostic core the NVDA add-on uses:

    POST /narrate  (image bytes)  ->  ChangeDetector gate  ->  NarrationEngine
                                  ->  {"changed": bool, "text": str, "reason": str}

No OS-specific accessibility integration — proving the platform-agnostic baseline.
It bundles a keyless "demo" provider so the whole capture -> gate -> narrate -> speak
loop is runnable anywhere (including this Raspberry Pi) without an API key; point it
at a real provider with --provider / env for actual narration.

Run:  python web/server.py               # demo provider, http://localhost:8765
      python web/server.py --provider anthropic --profile learning-chart

Security note: getDisplayMedia only works in a *secure context* — i.e. the page
must be served from localhost or over HTTPS. Opening http://<pi-ip>:8765 from
another machine will silently block screen capture. To use this Pi as the backend
from a laptop, tunnel it to localhost:  ssh -L 8765:localhost:8765 <pi>
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator, Sequence

# Run from a checkout without installing bitgil-core.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "core"))

from bitgil_core.change_detect import ChangeDetector  # noqa: E402
from bitgil_core.engine import NarrationEngine  # noqa: E402
from bitgil_core.live import iter_sentences  # noqa: E402
from bitgil_core.profiles import Profile, load_builtin_profiles  # noqa: E402
from bitgil_core.providers import build_provider  # noqa: E402
from bitgil_core.providers.base import (  # noqa: E402
	Message,
	VisionProvider,
	VisionResponse,
)
from bitgil_core.triage import DesktopEvent, InterruptTriage  # noqa: E402

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_PROFILES = os.path.join(_REPO, "profiles")


class DemoProvider(VisionProvider):
	"""Keyless stand-in so the pipeline runs with zero credentials.

	Returns canned Korean narration that changes each call, so streaming, the
	transcript, and speech interruption are all observable without an LLM.
	"""

	name = "demo"
	_LINES = [
		"화면 상단에 제목 표시줄이 보입니다.",
		"가운데에 본문 텍스트가 바뀌었습니다.",
		"오른쪽 아래에 알림이 하나 나타났습니다.",
		"버튼 두 개가 새로 생겼습니다: 확인, 취소.",
		"진행 표시줄이 절반쯤 찼습니다.",
	]

	def __init__(self) -> None:
		self._i = itertools.count()

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		line = self._LINES[next(self._i) % len(self._LINES)]
		return VisionResponse(text="(데모) " + line)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		yield self.complete(messages).text


def _load_profile(name: str) -> Profile:
	if os.path.isdir(_PROFILES):
		packs = load_builtin_profiles(_PROFILES)
		if name in packs:
			return packs[name]
	if name == "general":
		return Profile(name="general", system_prompt="화면을 간결히 설명하세요. 이전 해설이 있으면 무엇이 달라졌는지 중심으로 말하세요.")
	sys.exit(f"error: profile '{name}' not found in {_PROFILES}")


class Bitgil:
	"""Holds the reused core pipeline + a lock (single-user prototype)."""

	def __init__(self, provider_name: str, model: str, profile_name: str):
		self.profile = _load_profile(profile_name)
		if provider_name == "demo":
			provider: VisionProvider = DemoProvider()
		else:
			cfg = {}
			if model:
				cfg["model"] = model
			region = os.environ.get("BITGIL_AWS_REGION")
			if region:
				cfg["aws_region"] = region
			provider = build_provider(provider_name, cfg, speed=self.profile.speed)
		self.provider_name = provider_name
		self.engine = NarrationEngine(provider, self.profile)
		self.detector = ChangeDetector(hash_threshold=self.profile.hash_threshold)
		# Same provider drives event triage (ambient-copilot path).
		self.triage = InterruptTriage(provider)
		self._lock = threading.Lock()

	def config(self) -> dict:
		return {
			"provider": self.provider_name,
			"profile": self.profile.name,
			"density": self.profile.narration_density,
			"interval": self.profile.observe_interval,
			"max_image_dim": self.profile.max_image_dim or 1280,
		}

	def narrate(self, frame: bytes) -> dict:
		with self._lock:
			result = self.detector.evaluate(frame)
			if not result.changed:
				return {"changed": False, "text": "", "reason": "no-change"}
			text = self.engine.narrate(frame).text
			return {"changed": True, "text": text, "reason": result.reason}

	def narrate_stream(self, frame: bytes):
		"""Yield narration sentence-by-sentence for low perceived latency (F1)."""
		self._lock.acquire()
		try:
			if not self.detector.evaluate(frame).changed:
				return
			yield from iter_sentences(self.engine.narrate_stream(frame))
		finally:
			self._lock.release()

	def triage_event(self, data: dict) -> dict:
		"""Classify a structured desktop event → interrupt/queue/suppress.

		The ambient-copilot path (docs/ambient-copilot.md): a browser can't emit OS
		events, so this endpoint is driven by a future OS event source — or by curl
		for testing. Reuses bitgil_core.triage; safety guardrails are deterministic.
		"""
		event = DesktopEvent(
			kind=str(data.get("kind", "unknown")),
			source_app=str(data.get("source_app", "")),
			title=str(data.get("title", "")),
			text=str(data.get("text", "")),
			stole_focus=bool(data.get("stole_focus", False)),
		)
		with self._lock:
			d = self.triage.triage(event, user_goal=str(data.get("user_goal", "")))
		return {
			"action": d.action,
			"spoken": d.spoken,
			"category": d.category,
			"urgency": d.urgency,
			"needs_confirmation": d.needs_confirmation,
			"reason": d.reason,
		}


class Handler(BaseHTTPRequestHandler):
	bitgil: Bitgil = None  # set in main()

	def _send_json(self, obj: dict, status: int = 200) -> None:
		body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _send_file(self, path: str) -> None:
		if not os.path.isfile(path):
			self.send_error(404, "not found")
			return
		ctype = {
			".html": "text/html; charset=utf-8",
			".js": "text/javascript; charset=utf-8",
			".css": "text/css; charset=utf-8",
		}.get(os.path.splitext(path)[1], "application/octet-stream")
		with open(path, "rb") as f:
			body = f.read()
		self.send_response(200)
		self.send_header("Content-Type", ctype)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self):  # noqa: N802 (http.server API)
		if self.path == "/config":
			self._send_json(self.bitgil.config())
			return
		rel = "index.html" if self.path in ("/", "") else self.path.lstrip("/")
		# Prevent path traversal; serve only from the static dir.
		safe = os.path.normpath(os.path.join(_STATIC, rel))
		if not safe.startswith(_STATIC):
			self.send_error(403, "forbidden")
			return
		self._send_file(safe)

	def _body(self) -> bytes:
		length = int(self.headers.get("Content-Length", 0))
		return self.rfile.read(length) if length > 0 else b""

	def do_POST(self):  # noqa: N802
		if self.path == "/narrate":
			frame = self._body()
			if not frame:
				self._send_json({"error": "empty body"}, status=400)
				return
			try:
				self._send_json(self.bitgil.narrate(frame))
			except Exception as e:  # never crash the loop; surface as spoken error
				self._send_json({"changed": True, "text": f"오류: {e}", "reason": "error"})
			return

		if self.path == "/narrate/stream":
			self._stream_narrate(self._body())
			return

		if self.path == "/triage":
			try:
				data = json.loads(self._body() or b"{}")
			except ValueError:
				self._send_json({"error": "invalid json"}, status=400)
				return
			self._send_json(self.bitgil.triage_event(data))
			return

		self.send_error(404, "not found")

	def _stream_narrate(self, frame: bytes) -> None:
		"""Stream sentences as newline-delimited text (no Content-Length; close-terminated)."""
		self.send_response(200)
		self.send_header("Content-Type", "text/plain; charset=utf-8")
		self.send_header("Cache-Control", "no-cache")
		self.send_header("Connection", "close")
		self.end_headers()
		try:
			for sentence in self.bitgil.narrate_stream(frame):
				self.wfile.write((sentence + "\n").encode("utf-8"))
				self.wfile.flush()
		except Exception as e:
			try:
				self.wfile.write(("오류: " + str(e) + "\n").encode("utf-8"))
			except OSError:
				pass

	def log_message(self, fmt, *args):  # quiet the default per-request logging
		pass


def main() -> None:
	p = argparse.ArgumentParser(description="Bitgil web streaming backend")
	p.add_argument("--host", default="127.0.0.1")
	p.add_argument("--port", type=int, default=8765)
	p.add_argument("--provider", default=os.environ.get("BITGIL_PROVIDER", "demo"),
	               help="demo | anthropic | openai | gemini | ollama")
	p.add_argument("--model", default=os.environ.get("BITGIL_MODEL", ""))
	p.add_argument("--profile", default=os.environ.get("BITGIL_PROFILE", "general"))
	args = p.parse_args()

	Handler.bitgil = Bitgil(args.provider, args.model, args.profile)
	server = ThreadingHTTPServer((args.host, args.port), Handler)
	cfg = Handler.bitgil.config()
	print(f"Bitgil web on http://{args.host}:{args.port}  "
	      f"(provider={cfg['provider']} profile={cfg['profile']})")
	print("화면 공유는 secure context에서만 됩니다 — localhost로 열거나 HTTPS를 쓰세요.")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		server.shutdown()


if __name__ == "__main__":
	main()
