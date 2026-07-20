// Bitgil web client — a thin FrameSource + SpeechSink.
//
// It captures ANY device's screen via getDisplayMedia (platform-agnostic — no
// OS/screen-reader integration), downscales each frame client-side to cut
// upload + vision-token cost, and POSTs it to /narrate. The Python backend
// reuses bitgil_core's ChangeDetector + NarrationEngine and returns the text to
// speak, which we voice via the Web Speech API. This is the "screen is just a
// screen" baseline made runnable in any browser.

const $ = (id) => document.getElementById(id);
const video = $("video");
const canvas = $("canvas");
const ctx = canvas.getContext("2d");

let stream = null;
let timer = null;
let inFlight = false; // don't pile up frames while one is being narrated
let maxDim = 1280; // longest edge sent; mirrors the profile's max_image_dim lever

function setStatus(msg) {
	$("status").textContent = msg;
}

function addLog(text, reason) {
	const li = document.createElement("li");
	const tag = reason === "text" ? "텍스트 변화" : reason === "error" ? "오류" : "화면 변화";
	li.innerHTML = `<span class="reason">${tag}</span> `;
	li.appendChild(document.createTextNode(text));
	$("log").prepend(li);
}

function utter(text) {
	const u = new SpeechSynthesisUtterance(text);
	u.lang = "ko-KR";
	const ko = speechSynthesis.getVoices().find((v) => v.lang && v.lang.startsWith("ko"));
	if (ko) u.voice = ko;
	speechSynthesis.speak(u);
}

// One-shot narration: optionally cut in, then speak the whole thing.
function speak(text) {
	if (!$("speakOn").checked || !("speechSynthesis" in window)) return;
	if ($("interrupt").checked) speechSynthesis.cancel();
	utter(text);
}

// Streaming: only the first sentence of a frame may cut in; the rest queue so
// the phrases play back in order without talking over themselves.
function speakSentence(text, isFirst) {
	if (!$("speakOn").checked || !("speechSynthesis" in window)) return;
	if (isFirst && $("interrupt").checked) speechSynthesis.cancel();
	utter(text);
}

// Draw the current video frame into the canvas, downscaled so the longest edge
// is at most maxDim, then hand back a JPEG blob.
function grabFrame() {
	return new Promise((resolve) => {
		const vw = video.videoWidth, vh = video.videoHeight;
		if (!vw || !vh) return resolve(null);
		const scale = Math.min(1, maxDim / Math.max(vw, vh));
		canvas.width = Math.round(vw * scale);
		canvas.height = Math.round(vh * scale);
		ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
		canvas.toBlob((b) => resolve(b), "image/jpeg", 0.7);
	});
}

// One-shot: POST frame, get the whole narration back, then speak it.
async function narrateOnce(blob) {
	const res = await fetch("/narrate", {
		method: "POST",
		headers: { "Content-Type": "image/jpeg" },
		body: blob,
	});
	const data = await res.json();
	if (data.changed && data.text) {
		addLog(data.text, data.reason);
		speak(data.text);
	}
}

// Streaming: read newline-delimited sentences as they generate and speak each,
// so the user hears the first phrase without waiting for the whole response (F1).
async function narrateStream(blob) {
	const res = await fetch("/narrate/stream", {
		method: "POST",
		headers: { "Content-Type": "image/jpeg" },
		body: blob,
	});
	const reader = res.body.getReader();
	const dec = new TextDecoder();
	let buf = "";
	let first = true;
	const flush = (line) => {
		const s = line.trim();
		if (!s) return;
		addLog(s, "visual");
		speakSentence(s, first);
		first = false;
	};
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		buf += dec.decode(value, { stream: true });
		let idx;
		while ((idx = buf.indexOf("\n")) >= 0) {
			flush(buf.slice(0, idx));
			buf = buf.slice(idx + 1);
		}
	}
	flush(buf);
}

async function tick() {
	if (inFlight || !stream) return;
	const blob = await grabFrame();
	if (!blob) return;
	inFlight = true;
	try {
		if ($("streamOn").checked) await narrateStream(blob);
		else await narrateOnce(blob);
	} catch (e) {
		setStatus("백엔드 통신 오류: " + e.message);
	} finally {
		inFlight = false;
	}
}

async function start() {
	try {
		stream = await navigator.mediaDevices.getDisplayMedia({
			video: { frameRate: 2 },
			audio: false,
		});
	} catch (e) {
		setStatus("화면 공유가 취소되었거나 차단되었습니다 (localhost/HTTPS에서만 동작). " + e.message);
		return;
	}
	video.srcObject = stream;
	await video.play();
	// User stopped sharing from the browser's own UI.
	stream.getVideoTracks()[0].addEventListener("ended", stop);

	const intervalMs = Math.max(500, parseFloat($("interval").value || "1.5") * 1000);
	timer = setInterval(tick, intervalMs);
	$("toggle").textContent = "화면 공유 중지";
	setStatus("화면을 해설하는 중… (관찰 주기 " + intervalMs / 1000 + "초)");
}

function stop() {
	if (timer) clearInterval(timer);
	timer = null;
	if (stream) stream.getTracks().forEach((t) => t.stop());
	stream = null;
	speechSynthesis.cancel();
	$("toggle").textContent = "화면 공유 시작";
	setStatus("중지됨.");
}

$("toggle").addEventListener("click", () => (stream ? stop() : start()));

// Reflect backend config (provider/profile) and default the interval.
fetch("/config")
	.then((r) => r.json())
	.then((cfg) => {
		maxDim = cfg.max_image_dim || maxDim;
		if (cfg.interval) $("interval").value = cfg.interval;
		if (cfg.density) $("density").value = cfg.density;
		$("meta").textContent = `프로바이더: ${cfg.provider} · 프로파일: ${cfg.profile}`;
		if (cfg.provider === "demo") {
			$("meta").textContent += " · (데모 프로바이더 — 실제 해설은 --provider로 지정)";
		}
	})
	.catch(() => {});

// Voice list loads asynchronously in some browsers.
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
