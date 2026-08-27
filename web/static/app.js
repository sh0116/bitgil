// Bitgil web client — a thin FrameSource + SpeechSink, now conversational.
//
// It captures ANY device's screen via getDisplayMedia (platform-agnostic — no
// OS/screen-reader integration), downscales each frame client-side to cut
// upload + vision-token cost, and talks to the Python backend two ways:
//
//   POST /narrate        — the *auto* loop. The server's ChangeDetector gates it,
//                          so it only speaks on salient changes (or ?force=1).
//   POST /ask?q=<질문>    — the *conversation*. The user asks about the current
//                          frame; the server answers regardless of change.
//
// The design rule this file must not break: after sharing starts we don't dump
// the screen OCR-style. We say ONE line about what the screen is, then ASK whether
// the user wants detail — orientation first, communication over narration. And
// because screen narration is ALWAYS the model's guess (no source text to ground
// against), every reply is marked "모델" so a blind user knows what is inferred.

const $ = (id) => document.getElementById(id);
const video = $("video");
const canvas = $("canvas");
const ctx = canvas.getContext("2d");

let stream = null;
let timer = null;
let inFlight = false; // don't pile up frames while one is being narrated/answered
let maxDim = 1280; // longest edge sent; mirrors the profile's max_image_dim lever
let recognition = null; // Web Speech recognition, when the browser has it
let lastReply = "";   // 마지막 답의 본문 — "다시"로 다시 들려주기 위해 (모델 재호출 없이)

// 공유 직후 방향 잡기 질문. "전체적으로 무엇인지 한 문장"만 받고, 세부는 사용자가 청할 때.
const ORIENT_Q =
	"이 화면이 전체적으로 무슨 화면인지 딱 한 문장으로만 알려주세요. 세부 내용은 아직 읽지 마세요.";
// 한 줄 요약 뒤에 붙이는 안내 — 모델 호출 없이 결정적으로 같은 문장을 말합니다.
const OFFER =
	"자세한 설명을 원하시면 '자세히'라고 하거나 궁금한 걸 물어보세요. " +
	"예를 들어 '여기서 뭘 할 수 있어?', '무슨 버튼이 있어?'처럼요.";

function setStatus(msg) {
	$("status").textContent = msg;
}

// ---- 대화 기록 (말풍선) ------------------------------------------------------

function addUser(text) {
	const li = document.createElement("li");
	li.className = "msg user";
	li.innerHTML = '<span class="who">나</span> ';
	li.appendChild(document.createTextNode(text));
	$("log").appendChild(li);
	li.scrollIntoView({ block: "nearest" });
}

// 화면 해설은 언제나 모델의 말입니다. reason(변화/텍스트/요청/답)은 왜 이 말이 나왔는지를
// 작은 꼬리표로 남기되, "모델" 표시는 항상 붙습니다 — 무엇이 추측인지 알리는 안전장치.
function addReply(text, reason) {
	const li = document.createElement("li");
	li.className = "msg bot";
	const tag = document.createElement("span");
	tag.className = "tag model";
	tag.textContent = "모델";
	tag.setAttribute("aria-label", "모델이 화면을 보고 한 말입니다");
	li.appendChild(tag);
	const why = { text: "텍스트 변화", visual: "화면 변화", request: "요청",
		answer: "답", error: "오류", offer: "안내" }[reason];
	if (why) {
		const r = document.createElement("span");
		r.className = "reason";
		r.textContent = why;
		li.appendChild(r);
	}
	const body = document.createElement("p");
	body.className = "body";
	body.textContent = text;
	li.appendChild(body);
	$("log").appendChild(li);
	li.scrollIntoView({ block: "nearest" });
	if (reason !== "offer" && reason !== "error") lastReply = text;
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
	if (!$("speakOn").checked || !("speechSynthesis" in window) || !text) return;
	if ($("interrupt").checked) speechSynthesis.cancel();
	for (const part of String(text).split("\n")) {
		if (part.trim()) utter(part.trim());
	}
}

// Streaming: only the first sentence of a frame may cut in; the rest queue so
// the phrases play back in order without talking over themselves.
function speakSentence(text, isFirst) {
	if (!$("speakOn").checked || !("speechSynthesis" in window)) return;
	if (isFirst && $("interrupt").checked) speechSynthesis.cancel();
	utter(text);
}

function stopSpeech() {
	if ("speechSynthesis" in window) speechSynthesis.cancel();
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

// ---- 자동 관찰 루프 (변화가 크면 스스로 말한다) ------------------------------

// One-shot: POST frame, get the whole narration back, then speak it.
async function narrateOnce(blob, force) {
	const res = await fetch("/narrate" + (force ? "?force=1" : ""), {
		method: "POST",
		headers: { "Content-Type": "image/jpeg" },
		body: blob,
	});
	const data = await res.json();
	if (data.changed && data.text) {
		addReply(data.text, data.reason);
		speak(data.text);
	} else if (force) {
		setStatus("지금 화면에서 새로 설명할 것을 찾지 못했습니다.");
	}
}

// Streaming: read newline-delimited sentences as they generate and speak each.
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
		addReply(s, "visual");
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

// Observe one frame for the auto loop. `force` = the user pressed "지금 화면 설명".
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

// The periodic loop only *auto* narrates when the user left auto-notify on.
function tick() {
	if (!$("autoNotify").checked) return;
	observe(false);
}

// ---- 대화 (화면에 대해 묻고 답한다) ------------------------------------------

// Ask a question about the CURRENT frame. Everything the user can do — the text
// box, the mic, the quick buttons, "지금 화면 설명" — funnels here so they can't
// drift apart. "다시" is handled locally (re-speak) so it never re-calls the model.
async function ask(question) {
	const q = (question || "").trim();
	if (!q) return;
	if (!stream) { setStatus("먼저 화면 공유를 시작하세요."); return; }
	if (q === "다시") {
		if (lastReply) { setStatus("다시 들려 드립니다."); speak(lastReply); }
		else setStatus("아직 다시 들려 드릴 내용이 없습니다.");
		return;
	}
	if (inFlight) return;
	inFlight = true;   // 자동 관찰 루프가 같은 순간 프레임을 잡지 못하게 먼저 잠급니다.
	const blob = await grabFrame();
	if (!blob) {
		inFlight = false;
		setStatus("화면 프레임을 아직 읽지 못했습니다. 잠시 후 다시 시도하세요.");
		return;
	}
	addUser(q);
	$("send").disabled = true;
	setStatus("생각 중…");
	try {
		const res = await fetch("/ask?q=" + encodeURIComponent(q), {
			method: "POST",
			headers: { "Content-Type": "image/jpeg" },
			body: blob,
		});
		const data = await res.json();
		if (!res.ok) {
			const msg = data.text || data.error || "요청을 처리하지 못했습니다.";
			setStatus(msg);
			speak(msg);
			return;
		}
		addReply(data.text, data.reason || "answer");
		speak(data.text);
		setStatus("답했습니다. 더 궁금한 게 있으면 물어보세요.");
	} catch (e) {
		const msg = "백엔드 통신 오류: " + e.message;
		setStatus(msg);
		speak(msg);
	} finally {
		inFlight = false;
		$("send").disabled = false;
		$("ask").value = "";
		$("ask").focus();
	}
}

// Trigger ①: "지금 화면 설명" — a fuller, orientation-first description (not an
// OCR dump). It goes through the same /ask path so the answer stays conversational.
function describeNow() {
	if (!stream) { setStatus("먼저 화면 공유를 시작하세요."); return; }
	setStatus("지금 화면을 설명합니다…");
	ask("이 화면을 처음 보는 사람에게 전체 구조와 무엇을 할 수 있는지 차근차근 설명해줘");
}

// 공유 직후: 무슨 화면인지 한 줄로 말하고, 자세한 설명이 필요한지 물어봅니다.
async function orient() {
	inFlight = true;   // 자동 루프보다 먼저 잠가, 공유 직후 첫 프레임을 이 요약이 잡게 합니다.
	const blob = await grabFrame();
	if (!blob) { inFlight = false; return; }   // 프레임이 아직이면 사용자가 물어볼 때 다시 잡습니다.
	try {
		const res = await fetch("/ask?q=" + encodeURIComponent(ORIENT_Q), {
			method: "POST",
			headers: { "Content-Type": "image/jpeg" },
			body: blob,
		});
		const data = await res.json();
		if (res.ok && data.text) {
			addReply(data.text, "request");
			speak(data.text);
		}
	} catch (e) {
		setStatus("화면 요약을 가져오지 못했습니다: " + e.message);
	} finally {
		inFlight = false;
	}
	// 안내는 모델 호출과 무관하게 항상 결정적으로 붙습니다.
	addReply(OFFER, "offer");
	speak(OFFER);
	setStatus("무엇을 도와드릴까요? 자세한 설명이 필요하면 '자세히'라고 하거나 궁금한 걸 물어보세요.");
}

// ---- 공유 시작/중지 ----------------------------------------------------------

function setTalkEnabled(on) {
	for (const el of [$("ask"), $("send")]) el.disabled = !on;
	for (const b of document.querySelectorAll(".q")) b.disabled = !on;
	$("mic").disabled = !on || !recognition;
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
	setTalkEnabled(true);
	$("ask").focus();
	setStatus("화면을 살펴보는 중입니다. 무슨 화면인지 곧 알려 드릴게요…");
	orient();
}

function stop() {
	if (timer) clearInterval(timer);
	timer = null;
	if (stream) stream.getTracks().forEach((t) => t.stop());
	stream = null;
	speechSynthesis.cancel();
	$("toggle").textContent = "화면 공유 시작";
	$("describe").disabled = true;
	setTalkEnabled(false);
	setStatus("중지됨.");
}

// ---- 음성 입력 (있는 브라우저에서만) ----------------------------------------

function setupMic() {
	const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
	if (!Ctor) {
		$("mic").textContent = "🎙 음성 입력 (이 브라우저는 미지원)";
		return;
	}
	recognition = new Ctor();
	recognition.lang = "ko-KR";
	recognition.interimResults = false;
	recognition.continuous = false;
	recognition.addEventListener("result", (ev) => {
		const heard = ev.results[0][0].transcript;
		setStatus("들은 말: " + heard);
		ask(heard);
	});
	recognition.addEventListener("error", (ev) => {
		setStatus("음성 인식 오류: " + ev.error + ". 입력창에 타자로 물어봐도 됩니다.");
	});
	recognition.addEventListener("end", () => $("mic").setAttribute("aria-pressed", "false"));
	$("mic").addEventListener("click", () => {
		stopSpeech();   // 낭독 중에 마이크를 켜면 자기 목소리를 다시 듣습니다.
		try {
			recognition.start();
			$("mic").setAttribute("aria-pressed", "true");
			setStatus("듣고 있습니다. 말씀하세요.");
		} catch (e) {
			setStatus("음성 인식을 시작할 수 없습니다: " + e.message);
		}
	});
}

// ---- 배선 --------------------------------------------------------------------

$("toggle").addEventListener("click", () => (stream ? stop() : start()));
$("describe").addEventListener("click", describeNow);

$("askForm").addEventListener("submit", (e) => {
	e.preventDefault();
	ask($("ask").value);
});
for (const b of document.querySelectorAll(".q")) {
	b.addEventListener("click", () => ask(b.dataset.say));
}

document.addEventListener("keydown", (e) => {
	if (e.key === "Escape") { speechSynthesis.cancel(); return; }
	if (!e.altKey) return;
	const key = e.key.toLowerCase();
	if (key === "d") { e.preventDefault(); describeNow(); return; }
	if (key === "m" && !$("mic").disabled) { e.preventDefault(); $("mic").click(); }
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

setupMic();
setTalkEnabled(false);
// Voice list loads asynchronously in some browsers.
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
