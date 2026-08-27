#!/usr/bin/env python3
"""Bitgil web backend — a thin FrameSource/SpeechSink adapter over bitgil_core.

This is the "screen is just a screen" reference server (see docs/ambient-copilot.md
and docs/architecture.md). The browser captures any device's screen via
getDisplayMedia and speaks via the Web Speech API; this server does the heavy
lifting by reusing the EXACT platform-agnostic core the NVDA add-on uses:

    POST /narrate  (image bytes)  ->  ChangeDetector gate  ->  NarrationEngine
                                  ->  {"changed": bool, "text": str, "reason": str}

It also hosts the second input path — a whole exam paper instead of a live screen
(docs/qa.md S9, core/bitgil_core/tutor.py):

    POST /tutor/open (PDF bytes) ->  load_pdf  ->  overview, spoken, no model call
    POST /tutor/say  ({"text"})  ->  TutorSession.respond  ->  {text, grounded, ...}

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
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Run from a checkout without installing bitgil-core.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "core"))

from bitgil_core.change_detect import ChangeDetector  # noqa: E402
from bitgil_core.document import load_pdf  # noqa: E402
from bitgil_core.engine import NarrationEngine  # noqa: E402
from bitgil_core.goal import GoalTracker  # noqa: E402
from bitgil_core.profiles import Profile, load_builtin_profiles  # noqa: E402
from bitgil_core.providers import build_provider  # noqa: E402
from bitgil_core.providers.base import VisionProvider  # noqa: E402
from bitgil_core.review import ReviewLog  # noqa: E402
from bitgil_core.triage import DesktopEvent, InterruptTriage  # noqa: E402
from bitgil_core.tutor import TutorSession  # noqa: E402

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_PROFILES = os.path.join(_REPO, "profiles")

# 화면 해설 모드의 "자동으로 말할 만큼 큰 변화" 기준. 변화 감지 게이트(hash_threshold,
# 프로파일별 0.12 등)는 "프레임이 조금이라도 달라졌는가"를 보고 baseline을 갱신하는 반면,
# 이 문턱은 그보다 높아서 **사용자가 요청하지 않아도 끼어들 만큼 큰 변화**만 자동 낭독으로
# 넘깁니다. 나머지는 조용히 있다가 "지금 화면 설명"으로 부를 때 말합니다 — 도우미는 사용자가
# 원할 때 말해야지, 매 프레임을 무지성으로 읊지 않습니다.
_DEFAULT_SALIENT = 0.35


def _profile_or(name: str, fallback: Profile) -> Profile:
	"""Load a named profile pack, or fall back — never exits (unlike `_load_profile`)."""
	if os.path.isdir(_PROFILES):
		return load_builtin_profiles(_PROFILES).get(name, fallback)
	return fallback


def _load_profile(name: str) -> Profile:
	if os.path.isdir(_PROFILES):
		packs = load_builtin_profiles(_PROFILES)
		if name in packs:
			return packs[name]
	if name == "general":
		return Profile(name="general", system_prompt="화면을 간결히 설명하세요. 이전 해설이 있으면 무엇이 달라졌는지 중심으로 말하세요.")
	sys.exit(f"error: profile '{name}' not found in {_PROFILES}")


class _BadRequest(Exception):
	"""A malformed request the handler answers with HTTP 400.

	낭독 대상이 사용자다 — the message travels to the browser and is *spoken*, so every
	`raise _BadRequest(...)` below carries one actionable Korean sentence, not a code.
	"""


class Bitgil:
	"""Holds the reused core pipeline + a lock (single-user prototype)."""

	def __init__(self, provider_name: str, model: str, profile_name: str, base_url: str = "",
	             api_key: str = ""):
		self.provider_name = provider_name
		cfg = {}
		if model:
			cfg["model"] = model
		if base_url:
			cfg["base_url"] = base_url
		if api_key:
			# Only for endpoints that take a token on the wire (a gated OmniRoute
			# gateway). Vendor SDKs keep reading their own env vars; blank means the
			# provider falls back to whatever it finds in the environment.
			cfg["api_key"] = api_key
		region = os.environ.get("BITGIL_AWS_REGION")
		if region:
			cfg["aws_region"] = region
		profile = _load_profile(profile_name)
		# "demo" (keyless) routes through the same factory as every real provider.
		self.provider: VisionProvider = build_provider(
			provider_name, cfg, speed=profile.speed
		)
		# Same provider drives event triage (ambient-copilot path).
		self.triage = InterruptTriage(self.provider)
		# 문서 직독 모드는 도표 설명에서만 비전을 쓰므로, 보간 금지 하드 규칙이 있는
		# learning-chart 프로파일을 씁니다(없는 설치에서는 활성 프로파일로 폴백).
		self.tutor = TutorHost(self.provider, _profile_or("learning-chart", profile))
		self.goal = GoalTracker()
		self.salient_threshold = _DEFAULT_SALIENT
		self._lock = threading.Lock()
		self._apply_profile(_load_profile(profile_name))

	def _apply_profile(self, profile: Profile) -> None:
		self.profile = profile
		self.engine = NarrationEngine(self.provider, profile)
		self.detector = ChangeDetector(hash_threshold=profile.hash_threshold)

	def reconfigure(self, profile_name: str = "", density: str = "",
	                salient_threshold: float = None) -> dict:
		"""Rebuild the pipeline with a new profile / density (keeps the provider)."""
		with self._lock:
			profile = _load_profile(profile_name) if profile_name else self.profile
			if density and density != "profile":
				profile.narration_density = density
			if salient_threshold is not None:
				# 0(모든 변화 자동 낭독)..1(요청할 때만) 사이로 죕니다.
				self.salient_threshold = max(0.0, min(1.0, salient_threshold))
			self._apply_profile(profile)
			self.goal.clear()
		return self.config()

	def config(self) -> dict:
		return {
			"provider": self.provider_name,
			"profile": self.profile.name,
			"tutor_profile": self.tutor.profile.name,
			"profiles": self._profile_names(),
			"density": self.profile.narration_density,
			"interval": self.profile.observe_interval,
			"max_image_dim": self.profile.max_image_dim or 1280,
			"salient_threshold": self.salient_threshold,
		}

	@staticmethod
	def _profile_names() -> list:
		if os.path.isdir(_PROFILES):
			return sorted(load_builtin_profiles(_PROFILES).keys())
		return ["general"]

	def _salient(self, result) -> bool:
		"""자동으로 끼어들 만큼 큰 변화인가. 이미 계산된 visual_distance를 재사용합니다 —
		추가 모델 호출 없이, 텍스트가 바뀌었거나 시각 변화가 문턱을 넘으면 True."""
		return bool(result.text_changed or result.visual_distance >= self.salient_threshold)

	def narrate(self, frame: bytes, force: bool = False) -> dict:
		"""화면 프레임을 해설합니다.

		`force`는 사용자가 **직접 요청한** 경우("지금 화면 설명")로, 변화 여부와 무관하게
		해설합니다. 그렇지 않은 자동 관찰에서는 **큰 변화만** 말합니다 — 매 프레임을 읊는 대신
		조용히 지켜보다가, 사용자가 부르거나 화면이 크게 바뀔 때만 소통합니다.
		"""
		with self._lock:
			result = self.detector.evaluate(frame)
			salient = self._salient(result)
			if not force and not salient:
				# 조용히 있습니다. no-change(전혀 안 바뀜)와 minor(조금 바뀜)를 구분해
				# 클라이언트가 "관찰 중"임을 알 수 있게 합니다.
				reason = "no-change" if not result.changed else "minor"
				return {"changed": False, "salient": False,
				        "visual_distance": round(result.visual_distance, 3),
				        "text": "", "reason": reason}
			text = self.engine.narrate(frame).text
			self.goal.note(text)  # feed activity context for triage relevance
			return {"changed": True, "salient": salient,
			        "visual_distance": round(result.visual_distance, 3),
			        "text": text, "reason": "request" if force else (result.reason or "visual")}

	def narrate_stream(self, frame: bytes, force: bool = False):
		"""Yield narration sentence-by-sentence for low perceived latency (F1).

		The pipeline lock is deliberately held for the whole stream: this is a
		single-user prototype (see class docstring), so serializing pipeline access
		— rather than interleaving a second request's mutations of the shared
		engine/detector/goal — is the correct trade-off here. A multi-user server
		would give each session its own engine instead; tracked in docs/qa.md §5.

		자동 관찰에서는 큰 변화만 스트리밍합니다(narrate와 같은 규칙). `force`면 요청으로 보고
		변화와 무관하게 해설합니다.
		"""
		self._lock.acquire()
		try:
			if not force and not self._salient(self.detector.evaluate(frame)):
				return
			spoken = []
			# narrate_stream already yields whole, glossary-applied sentences.
			for sentence in self.engine.narrate_stream(frame):
				spoken.append(sentence)
				yield sentence
			self.goal.note(" ".join(spoken))
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
		# Explicit goal wins; otherwise fall back to recent activity context.
		goal = str(data.get("user_goal", "")) or self.goal.context()
		with self._lock:
			d = self.triage.triage(event, user_goal=goal)
		return {
			"action": d.action,
			"spoken": d.spoken,
			"category": d.category,
			"urgency": d.urgency,
			"needs_confirmation": d.needs_confirmation,
			"reason": d.reason,
		}


def _reply_json(reply) -> dict:
	"""A TutorReply on the wire. `grounded` is the whole point of shipping it.

	The browser must be able to *show and say* which of two sentence kinds it just
	received — the exam paper's own words, or the model's. Dropping this field would
	make the web client less honest than the CLI (`scripts/bitgil_tutor.py::_print`).
	"""
	return {
		"text": reply.text,
		"grounded": reply.grounded,
		"unsupported": list(reply.unsupported or []),
	}


class TutorHost:
	"""The document-tutor session behind `/tutor/*` — one open exam paper at a time.

	Two things are worth explaining here.

	**Why the upload is written to a temp file.** 도표 렌더링(`document.render_page`)은
	poppler `pdftoppm`을 **파일 경로로** 호출하므로 바이트만 들고 있을 수 없습니다. 그래서
	업로드본을 임시 디렉터리에 두고, 시험지를 닫거나 다른 시험지를 열 때 **지웁니다** — 화면
	프레임을 디스크에 남기지 않는 것과 같은 규칙입니다(시험지에는 학생 이름이 적혀 있을 수 있습니다).

	**Why the tutor gets its own engine.** 화면 해설 파이프라인과 상태(최근 해설 문맥,
	변화 감지)를 공유하면 시험지 대화가 화면 해설 문맥에 섞여 들어갑니다. 프로바이더만 공유하고
	엔진·복습 노트는 세션마다 새로 만듭니다.
	"""

	def __init__(self, provider: VisionProvider, profile: Profile):
		self.provider = provider
		self.profile = profile
		self.session: TutorSession = None
		self.review: ReviewLog = None
		self.name = ""
		self._dir = ""
		self._lock = threading.Lock()

	# ---- 열기 / 닫기 ---------------------------------------------------------------

	def open_document(self, data: bytes, name: str) -> dict:
		"""업로드된 PDF를 열고 **개요를 돌려줍니다**(모델 호출 없음).

		거절은 여기서 끝냅니다 — 스캔 PDF를 조용히 비전 경로로 흘리면 사용자는 근거 있는
		낭독과 모델 추측을 구분할 수 없습니다(`document.load_pdf` 참고).
		"""
		if not data:
			raise _BadRequest("PDF 파일을 선택해 주세요.")
		if not data.startswith(b"%PDF"):
			raise _BadRequest(
				"PDF 파일만 읽을 수 있습니다. 시험지를 PDF로 저장해서 올려 주세요."
			)
		safe = _safe_name(name) or "시험지.pdf"
		tmpdir = tempfile.mkdtemp(prefix="bitgil-tutor-")
		path = os.path.join(tmpdir, safe)
		try:
			with open(path, "wb") as f:
				f.write(data)
			document = load_pdf(path)
		except (ValueError, RuntimeError, OSError) as e:
			shutil.rmtree(tmpdir, ignore_errors=True)
			raise _BadRequest(str(e)) from None

		with self._lock:
			self._forget()
			self._dir = tmpdir
			self.name = safe
			self.review = ReviewLog(
				title=safe,
				clock=lambda: time.strftime("%H:%M:%S"),
				provider=self.provider.name,
				model=getattr(self.provider, "model", ""),
			)
			# 엔진에는 노트를 주지 않습니다 — 기록은 `TutorSession`이 응답 단위로 합니다.
			# 둘 다 적으면 도표 설명이 두 번 남고(엔진의 원본 + 세션의 고지 붙은 문장),
			# 같은 문장을 두 번 들은 것이 학습 기록상 두 번 일어난 일은 아닙니다.
			engine = NarrationEngine(self.provider, self.profile)
			self.session = TutorSession(document, engine, review_log=self.review)
			reply = self.session.overview()
			return {
				"name": safe,
				"title": document.title,
				"pages": len(document.pages),
				"questions": [q.number for q in document.questions],
				"figures": document.figure_numbers(),
				**_reply_json(reply),
			}

	def close(self) -> dict:
		with self._lock:
			self._forget()
		return {"closed": True}

	def _forget(self) -> None:
		"""세션과 업로드본을 버립니다. 호출자가 락을 잡고 있어야 합니다."""
		if self._dir:
			shutil.rmtree(self._dir, ignore_errors=True)
		self._dir = ""
		self.name = ""
		self.session = None
		self.review = None

	# ---- 대화 --------------------------------------------------------------------

	def say(self, utterance: str) -> dict:
		"""학생의 한 줄을 `TutorSession.respond`로 — 라우팅 규칙은 CLI와 같은 코드입니다."""
		with self._lock:
			if self.session is None:
				raise _BadRequest(
					"먼저 시험지 PDF를 올려 주세요. '시험지 열기'에서 파일을 선택하면 됩니다."
				)
			started = time.monotonic()
			try:
				reply = _reply_json(self.session.respond(utterance))
			except Exception as e:
				# 프로바이더·poppler 실패가 그대로 음성으로 읽히므로, 상태코드가 아니라
				# 무엇을 하면 되는지가 담긴 문장을 올립니다(`/narrate`와 같은 규약).
				reply = {"text": f"오류: {e}", "grounded": False, "unsupported": []}
			current = self.session.current
			return {
				**reply,
				"elapsed": round(time.monotonic() - started, 2),
				"current": current.number if current else None,
			}

	def review_markdown(self) -> str:
		with self._lock:
			if self.review is None:
				raise _BadRequest("아직 저장할 대화가 없습니다. 시험지를 열고 대화해 주세요.")
			return self.review.to_markdown()


def _force(query: str) -> bool:
	"""쿼리스트링의 force 플래그 — 사용자가 직접 요청한 해설인지(변화 게이트를 건너뜁니다)."""
	return urllib.parse.parse_qs(query).get("force", ["0"])[0] in ("1", "true", "yes")


def _safe_name(name: str) -> str:
	"""업로드된 파일명을 파일 이름 한 조각으로 축소(경로 탈출·제어문자 차단, 한글 유지)."""
	base = os.path.basename((name or "").replace("\\", "/")).strip()
	cleaned = "".join(c for c in base if c.isprintable() and c not in '/:*?"<>|')
	return cleaned.lstrip(".")[:80]


class Handler(BaseHTTPRequestHandler):
	bitgil: Bitgil = None  # set in main()
	# A captured screen frame is a few hundred KB; cap well above that so a bogus
	# or hostile Content-Length can't make the server try to buffer gigabytes.
	_MAX_BODY = 32 * 1024 * 1024

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
		path = self.path.partition("?")[0]
		if path == "/config":
			self._send_json(self.bitgil.config())
			return
		if path == "/tutor/review":
			try:
				body = self.bitgil.tutor.review_markdown().encode("utf-8")
			except _BadRequest as e:
				self._send_json({"error": str(e), "text": str(e)}, status=400)
				return
			self.send_response(200)
			self.send_header("Content-Type", "text/markdown; charset=utf-8")
			# 복습 노트는 학습물로 저장되는 파일이므로 다운로드로 내보냅니다(고지·출처 포함).
			self.send_header("Content-Disposition", 'attachment; filename="bitgil-review.md"')
			self.send_header("Content-Length", str(len(body)))
			self.end_headers()
			self.wfile.write(body)
			return
		rel = "index.html" if path in ("/", "") else path.lstrip("/")
		# Prevent path traversal; serve only from *inside* the static dir. The
		# separator on the prefix matters — a bare startswith(_STATIC) would also
		# accept a sibling like "<static>-secrets/".
		safe = os.path.normpath(os.path.join(_STATIC, rel))
		if safe != _STATIC and not safe.startswith(_STATIC + os.sep):
			self.send_error(403, "forbidden")
			return
		self._send_file(safe)

	def _body(self) -> bytes:
		raw = self.headers.get("Content-Length", "")
		try:
			length = int(raw) if raw else 0
		except ValueError:
			raise _BadRequest("invalid Content-Length")
		if length < 0 or length > self._MAX_BODY:
			raise _BadRequest("body too large")
		return self.rfile.read(length) if length > 0 else b""

	def do_POST(self):  # noqa: N802
		try:
			body = self._body()
		except _BadRequest as e:
			self._send_json({"error": str(e)}, status=400)
			return
		path, _, query = self.path.partition("?")

		if path == "/tutor/open":
			# 파일명은 쿼리로 받습니다(HTTP 헤더는 latin-1이라 한글 파일명이 깨집니다).
			name = urllib.parse.parse_qs(query).get("name", [""])[0]
			try:
				self._send_json(self.bitgil.tutor.open_document(body, name))
			except _BadRequest as e:
				# error(개발자용)와 text(낭독용)를 함께 — 클라이언트는 text를 읽습니다.
				self._send_json({"error": str(e), "text": str(e)}, status=400)
			return

		if path == "/tutor/say":
			try:
				data = json.loads(body or b"{}")
			except ValueError:
				self._send_json({"error": "invalid json"}, status=400)
				return
			try:
				self._send_json(self.bitgil.tutor.say(str(data.get("text", ""))))
			except _BadRequest as e:
				self._send_json({"error": str(e), "text": str(e)}, status=400)
			return

		if path == "/tutor/close":
			self._send_json(self.bitgil.tutor.close())
			return

		if path == "/narrate":
			if not body:
				self._send_json({"error": "empty body"}, status=400)
				return
			try:
				self._send_json(self.bitgil.narrate(body, force=_force(query)))
			except Exception as e:  # never crash the loop; surface as spoken error
				self._send_json({"changed": True, "text": f"오류: {e}", "reason": "error"})
			return

		if path == "/narrate/stream":
			self._stream_narrate(body, force=_force(query))
			return

		if path == "/triage":
			try:
				data = json.loads(body or b"{}")
			except ValueError:
				self._send_json({"error": "invalid json"}, status=400)
				return
			self._send_json(self.bitgil.triage_event(data))
			return

		if path == "/configure":
			try:
				data = json.loads(body or b"{}")
			except ValueError:
				self._send_json({"error": "invalid json"}, status=400)
				return
			try:
				salient = data.get("salient_threshold", None)
				cfg = self.bitgil.reconfigure(
					profile_name=str(data.get("profile", "")),
					density=str(data.get("density", "")),
					salient_threshold=float(salient) if salient is not None else None,
				)
			except (TypeError, ValueError):
				self._send_json({"error": "salient_threshold must be a number"}, status=400)
				return
			except SystemExit as e:  # unknown profile name
				self._send_json({"error": str(e)}, status=400)
				return
			self._send_json(cfg)
			return

		self.send_error(404, "not found")

	def _stream_narrate(self, frame: bytes, force: bool = False) -> None:
		"""Stream sentences as newline-delimited text (no Content-Length; close-terminated)."""
		self.send_response(200)
		self.send_header("Content-Type", "text/plain; charset=utf-8")
		self.send_header("Cache-Control", "no-cache")
		self.send_header("Connection", "close")
		self.end_headers()
		try:
			for sentence in self.bitgil.narrate_stream(frame, force=force):
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
	               help="demo | omniroute | anthropic | openai | gemini | ollama")
	p.add_argument("--model", default=os.environ.get("BITGIL_MODEL", ""))
	p.add_argument("--profile", default=os.environ.get("BITGIL_PROFILE", "general"))
	p.add_argument("--base-url", default=os.environ.get("BITGIL_BASE_URL", ""),
	               help="provider endpoint (ollama / omniroute); blank = its default")
	p.add_argument("--api-key", default="",
	               help="token for a gated OmniRoute gateway; blank = read "
	                    "OMNIROUTE_API_KEY / BITGIL_API_KEY from the environment")
	args = p.parse_args()

	Handler.bitgil = Bitgil(args.provider, args.model, args.profile, args.base_url,
	                        args.api_key)
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
