"""End-to-end HTTP smoke test for the web backend (web/server.py).

Runs the real ThreadingHTTPServer with the keyless DemoProvider on an ephemeral
port and drives it over HTTP — the same path the browser client and the QA
scenarios in docs/qa.md use. No network, no API key. This is the only coverage
web/server.py has, so it deliberately checks the contract edges: change-detection
gating, the streaming response, triage safety, and the malformed-request 400s /
path-traversal 403s.
"""

import importlib.util
import io
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image, ImageDraw

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER_PATH = os.path.join(_REPO, "web", "server.py")


def _load_server_module():
	spec = importlib.util.spec_from_file_location("bitgil_web_server", _SERVER_PATH)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


server = _load_server_module()


def _frame(kind: str) -> bytes:
	"""Two structurally-different frames so their perceptual hashes differ.

	Solid colours and near-mirror layouts can share a phash (flat/symmetric DCT),
	so pick shapes with clearly different low-frequency structure — measured phash
	distance ≈ 0.48, well above the 0.12 gate threshold.
	"""
	img = Image.new("RGB", (128, 128), "white")
	d = ImageDraw.Draw(img)
	if kind == "a":
		d.rectangle([0, 0, 63, 127], fill="black")   # left half filled
	else:
		d.ellipse([32, 32, 96, 96], fill="black")    # centred disc
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


@pytest.fixture()
def base_url():
	"""A fresh server + Bitgil per test (isolated change-detector state)."""
	server.Handler.bitgil = server.Bitgil("demo", "", "general")
	httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
	port = httpd.server_address[1]
	t = threading.Thread(target=httpd.serve_forever, daemon=True)
	t.start()
	try:
		yield f"http://127.0.0.1:{port}"
	finally:
		httpd.shutdown()
		httpd.server_close()
		t.join(timeout=2)


def _post(url, data, headers=None, method="POST"):
	req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
	try:
		with urllib.request.urlopen(req, timeout=5) as r:
			return r.status, r.read()
	except urllib.error.HTTPError as e:
		return e.code, e.read()


def _get(url):
	try:
		with urllib.request.urlopen(url, timeout=5) as r:
			return r.status, r.read()
	except urllib.error.HTTPError as e:
		return e.code, e.read()


def _json_post(url, obj):
	status, body = _post(url, json.dumps(obj).encode("utf-8"))
	return status, json.loads(body) if body else None


def test_config_reports_demo_provider(base_url):
	status, body = _get(base_url + "/config")
	assert status == 200
	cfg = json.loads(body)
	assert cfg["provider"] == "demo"
	assert "general" in cfg["profiles"]


def test_narrate_change_detection_gates_llm(base_url):
	# First frame is always "new"; re-sending it must gate (no-change); a
	# structurally different frame narrates again. Body is raw image bytes.
	status, body = _post(base_url + "/narrate", _frame("a"))
	first = json.loads(body)
	assert status == 200 and first["changed"] is True and first["text"]

	status, body = _post(base_url + "/narrate", _frame("a"))
	same = json.loads(body)
	assert same["changed"] is False and same["reason"] == "no-change"

	status, body = _post(base_url + "/narrate", _frame("b"))
	changed = json.loads(body)
	assert changed["changed"] is True and changed["text"]


def test_narrate_empty_body_is_400(base_url):
	status, body = _post(base_url + "/narrate", b"")
	assert status == 400
	assert json.loads(body)["error"] == "empty body"


def test_narrate_stream_yields_sentences(base_url):
	status, body = _post(base_url + "/narrate/stream", _frame("a"))
	assert status == 200
	text = body.decode("utf-8")
	assert text.strip()  # at least one sentence streamed
	assert "데모" in text


def test_triage_scam_interrupts_with_confirmation(base_url):
	status, d = _json_post(
		base_url + "/triage",
		{"kind": "dialog", "title": "축하합니다!", "text": "무료 상품에 당첨! 지금 클릭",
		 "stole_focus": True},
	)
	assert status == 200
	assert d["action"] == "interrupt"
	assert d["reason"] == "suspected-scam"
	assert d["needs_confirmation"] is True


def test_triage_permission_prompt_caught_by_heuristic(base_url):
	# DemoProvider returns no JSON, so this exercises the deterministic heuristic
	# fallback path — the security phrasing must still be gated.
	status, d = _json_post(
		base_url + "/triage",
		{"kind": "permission", "title": "권한 요청", "text": "카메라 접근을 허용하시겠습니까?"},
	)
	assert status == 200
	assert d["action"] == "interrupt"
	assert d["needs_confirmation"] is True


def test_triage_invalid_json_is_400(base_url):
	status, body = _post(base_url + "/triage", b"{not json")
	assert status == 400
	assert json.loads(body)["error"] == "invalid json"


def test_configure_unknown_profile_is_400(base_url):
	status, body = _post(base_url + "/configure", json.dumps({"profile": "does-not-exist"}).encode())
	assert status == 400


def test_configure_switches_profile(base_url):
	status, d = _json_post(base_url + "/configure", {"profile": "learning-chart"})
	assert status == 200
	assert d["profile"] == "learning-chart"


def test_path_traversal_is_blocked(base_url):
	# normpath escapes the static dir → 403 forbidden (never serves server.py).
	status, _ = _get(base_url + "/../server.py")
	assert status in (403, 404)
	status, _ = _get(base_url + "/../../etc/passwd")
	assert status in (403, 404)


def test_malformed_content_length_is_400(base_url):
	# Empty body: the server rejects the bogus Content-Length before reading any
	# body, so there's nothing left unread in the socket. Sending actual bytes
	# here races on Windows — closing the connection with an unread request body
	# makes the OS abort it (WinError 10053) before the client reads the 400.
	status, body = _post(
		base_url + "/narrate", b"",
		headers={"Content-Length": "not-a-number"},
	)
	assert status == 400


def test_unknown_post_route_is_404(base_url):
	status, _ = _post(base_url + "/nope", b"{}")
	assert status == 404
