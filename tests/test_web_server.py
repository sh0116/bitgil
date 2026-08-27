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
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image, ImageDraw
from pdf_fixture import pdf_with_text, scanned_pdf

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


# --- 시험지 대화 모드 (/tutor/*) -------------------------------------------------
#
# 브라우저에서 PDF를 올려 대화하는 경로(docs/qa.md S9). 여기서 지키는 계약은 두 가지다:
# 원문 낭독은 모델을 거치지 않는다는 것(`grounded`)과, 거절·오류가 조치 가능한 한국어
# 문장으로 온다는 것(그 문장이 사용자에게 **음성으로 읽힌다**).

_EXAM = ["2026 mock exam", "1. Read the chart below.", "2. What is shown?"]


def _open_exam(base_url, data=None, name="exam.pdf"):
	body = pdf_with_text(_EXAM) if data is None else data
	url = base_url + "/tutor/open?name=" + urllib.parse.quote(name)
	status, raw = _post(url, body, headers={"Content-Type": "application/pdf"})
	return status, json.loads(raw)


def test_tutor_open_answers_with_the_overview_and_the_question_list(base_url):
	status, d = _open_exam(base_url)
	assert status == 200
	assert d["grounded"] is True          # 개요는 원문 — 모델을 거치지 않는다
	assert d["title"] == "2026 mock exam"  # 파일명이 아니라 인쇄된 머리글
	assert d["questions"] == [1, 2]
	assert "문항 2개" in d["text"]
	assert d["text"].rstrip().endswith("문항 번호만 말해도 됩니다.")   # 설명하고 기다린다


def test_tutor_say_reads_the_question_from_the_text_layer(base_url):
	_open_exam(base_url)
	status, d = _json_post(base_url + "/tutor/say", {"text": "1번 읽어줘"})
	assert status == 200
	assert d["grounded"] is True
	assert "Read the chart below." in d["text"]
	assert d["current"] == 1
	assert d["unsupported"] == []


def test_tutor_say_before_a_document_says_what_to_do(base_url):
	# 상태코드만 오면 낭독으로는 아무 정보가 아니다 — 무엇을 하면 되는지가 문장에 있어야 한다.
	status, d = _json_post(base_url + "/tutor/say", {"text": "1번 읽어줘"})
	assert status == 400
	assert "시험지" in d["text"] and "PDF" in d["text"]


def test_tutor_open_rejects_a_non_pdf_with_actionable_korean(base_url):
	status, d = _open_exam(base_url, data=b"not a pdf at all", name="notes.txt")
	assert status == 400
	assert "PDF" in d["text"]


def test_tutor_open_rejects_a_scanned_pdf(base_url):
	# 텍스트 레이어가 없으면 이 모드가 약속한 정확도가 성립하지 않는다 → 여기서 멈춘다.
	status, d = _open_exam(base_url, data=scanned_pdf(), name="scan.pdf")
	assert status == 400
	assert "스캔 PDF" in d["text"]


def test_tutor_open_is_400_for_an_empty_upload(base_url):
	status, d = _open_exam(base_url, data=b"")
	assert status == 400
	assert "PDF" in d["text"]


def test_tutor_open_sanitises_a_traversing_file_name(base_url):
	status, d = _open_exam(base_url, name="../../etc/passwd.pdf")
	assert status == 200
	assert d["name"] == "passwd.pdf"        # 경로 조각은 남지 않는다


def test_tutor_review_export_carries_the_machine_generated_notice(base_url):
	_open_exam(base_url)
	_json_post(base_url + "/tutor/say", {"text": "1번 읽어줘"})
	status, body = _get(base_url + "/tutor/review")
	assert status == 200
	text = body.decode("utf-8")
	assert "AI가" in text                   # 기계 생성 고지는 항상 붙는다 (B1)
	assert "Read the chart below." in text


def test_tutor_review_records_a_figure_description_once(base_url):
	# 엔진과 세션이 같은 노트에 각각 적으면 도표 설명이 두 번 남는다 — 같은 문장을 두 번
	# 들은 것이 학습 기록상 두 번 일어난 일은 아니다(`TutorSession.repeat`과 같은 이유).
	_open_exam(base_url)
	status, d = _json_post(base_url + "/tutor/say", {"text": "도표 설명해줘"})
	assert status == 200 and d["grounded"] is False
	_, body = _get(base_url + "/tutor/review")
	assert body.decode("utf-8").count(d["text"]) == 1


def test_tutor_review_without_a_document_is_400(base_url):
	status, body = _get(base_url + "/tutor/review")
	assert status == 400
	assert "시험지" in json.loads(body)["text"]


def test_tutor_close_forgets_the_document_and_deletes_the_upload(base_url):
	_open_exam(base_url)
	uploaded = server.Handler.bitgil.tutor._dir
	assert os.path.isdir(uploaded)
	status, d = _json_post(base_url + "/tutor/close", {})
	assert status == 200 and d["closed"] is True
	# 시험지에는 학생 이름이 적혀 있을 수 있다 — 업로드본을 남기지 않는다.
	assert not os.path.exists(uploaded)
	status, _ = _json_post(base_url + "/tutor/say", {"text": "1번"})
	assert status == 400


def test_tutor_opening_a_second_exam_deletes_the_first_upload(base_url):
	_open_exam(base_url)
	first = server.Handler.bitgil.tutor._dir
	_open_exam(base_url, name="second.pdf")
	assert not os.path.exists(first)
	assert server.Handler.bitgil.tutor.name == "second.pdf"


def test_tutor_page_is_served(base_url):
	status, body = _get(base_url + "/tutor.html")
	assert status == 200
	assert b"tutor.js" in body


def test_every_asset_the_tutor_page_references_is_served(base_url):
	# 스크립트·스타일 경로가 하나만 어긋나도 화면은 **조용히** 빈 페이지가 된다. 화면을 못
	# 보는 사용자에게 "아무 일도 일어나지 않음"은 진단할 수 없는 고장이라, 여기서 고정한다.
	# (Pi에는 headless 브라우저가 없어 렌더링 자체는 실기기 확인 대상 — docs/qa.md §5.)
	_, page = _get(base_url + "/tutor.html")
	html = page.decode("utf-8")
	refs = re.findall(r'(?:src|href)="([^"#:]+)"', html)
	assert "tutor.js" in refs and "styles.css" in refs
	for ref in refs:
		status, body = _get(base_url + "/" + ref.lstrip("/"))
		assert status == 200, f"{ref} → {status}"
		assert body, f"{ref} 이(가) 비어 있다"


def test_config_names_the_profile_used_for_figures(base_url):
	# 도표 설명은 보간 금지 하드 규칙이 있는 learning-chart로 돈다(A2).
	status, body = _get(base_url + "/config")
	assert status == 200
	assert json.loads(body)["tutor_profile"] == "learning-chart"
