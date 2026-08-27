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

// One-shot: POST frame, get the whole narration back, then speak it. `force` is
// set when the user asked ("지금 화면 설명") — the server then speaks regardless of
// how much the screen changed. Without it the server stays quiet unless the change
// is salient, so the auto loop no longer reads every frame out loud.
async function narrateOnce(blob, force) {
	const res = await fetch("/narrate" + (force ? "?force=1" : ""), {
		method: "POST",
		headers: { "Content-Type": "image/jpeg" },
		body: blob,
	});
	const data = await res.json();
	if (data.changed && data.text) {
		addLog(data.text, data.reason);
		speak(data.text);
	} else if (force) {
		// 요청했는데 할 말이 없으면 침묵은 고장처럼 들립니다 — 무슨 상태인지 말합니다.
		setStatus("지금 화면에서 새로 설명할 것을 찾지 못했습니다.");
	}
}

// Streaming: read newline-delimited sentences as they generate and speak each,
// so the user hears the first phrase without waiting for the whole response (F1).
async function narrateStream(blob, force) {
	const res = await fetch("/narrate/stream" + (force ? "?force=1" : ""), {
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

// Observe one frame. `force` = the user asked; otherwise the server decides whether
// the change is worth speaking. One request at a time so frames don't pile up.
async function observe(force) {
	if (inFlight || !stream) return;
	const blob = await grabFrame();
	if (!blob) return;
	inFlight = true;
	try {
		if ($("streamOn").checked) await narrateStream(blob, force);
		else await narrateOnce(blob, force);
	} catch (e) {
		setStatus("백엔드 통신 오류: " + e.message);
	} finally {
		inFlight = false;
	}
}

// The periodic loop only *auto* narrates when the user left auto-notify on; even
// then the server speaks only on salient changes. With it off, the screen is
// watched but silent until "지금 화면 설명".
function tick() {
	if (!$("autoNotify").checked) return;
	observe(false);
}

// Trigger ①: the user explicitly asks for the current screen, right now.
function describeNow() {
	if (!stream) { setStatus("먼저 화면 공유를 시작하세요."); return; }
	if (inFlight) return;
	setStatus("지금 화면을 설명합니다…");
	observe(true);
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
	$("describe").disabled = false;
	setStatus(
		"화면을 지켜보는 중입니다. 크게 바뀌면 알려 드리고, 언제든 “지금 화면 설명”(Alt+D)을 누르면 설명합니다.",
	);
}

function stop() {
	if (timer) clearInterval(timer);
	timer = null;
	if (stream) stream.getTracks().forEach((t) => t.stop());
	stream = null;
	speechSynthesis.cancel();
	$("toggle").textContent = "화면 공유 시작";
	$("describe").disabled = true;
	setStatus("중지됨.");
}

$("toggle").addEventListener("click", () => (stream ? stop() : start()));
$("describe").addEventListener("click", describeNow);

document.addEventListener("keydown", (e) => {
	if (e.key === "Escape") { speechSynthesis.cancel(); return; }
	if (e.altKey && e.key.toLowerCase() === "d") { e.preventDefault(); describeNow(); }
});

function applyConfig(cfg) {
	maxDim = cfg.max_image_dim || maxDim;
	if (cfg.interval) $("interval").value = cfg.interval;
	if (cfg.density) $("density").value = cfg.density;
	if (typeof cfg.salient_threshold === "number") $("sensitivity").value = cfg.salient_threshold;
	if (Array.isArray(cfg.profiles)) {
		const sel = $("profile");
		sel.innerHTML = "";
		for (const name of cfg.profiles) {
			const o = document.createElement("option");
			o.value = o.textContent = name;
			if (name === cfg.profile) o.selected = true;
			sel.appendChild(o);
		}
	}
	$("meta").textContent = `프로바이더: ${cfg.provider} · 프로파일: ${cfg.profile}`;
	if (cfg.provider === "demo") {
		$("meta").textContent += " · (데모 프로바이더 — 실제 해설은 --provider로 지정)";
	}
}

// Push profile / density changes to the backend so they take effect.
async function reconfigure() {
	try {
		const res = await fetch("/configure", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				profile: $("profile").value,
				density: $("density").value,
				salient_threshold: parseFloat($("sensitivity").value),
			}),
		});
		const cfg = await res.json();
		if (cfg.error) { setStatus("설정 오류: " + cfg.error); return; }
		applyConfig(cfg);
		setStatus(`설정 적용됨 — 프로파일 ${cfg.profile}, 밀도 ${cfg.density}`);
	} catch (e) {
		setStatus("설정 통신 오류: " + e.message);
	}
}
$("profile").addEventListener("change", reconfigure);
$("density").addEventListener("change", reconfigure);
$("sensitivity").addEventListener("change", reconfigure);

// Reflect backend config on load.
fetch("/config")
	.then((r) => r.json())
	.then(applyConfig)
	.catch(() => setStatus("백엔드에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요."));

// Voice list loads asynchronously in some browsers.
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
