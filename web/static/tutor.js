// Bitgil tutor client — 시험지 PDF를 올려 대화하는 화면.
//
// The screen-sharing client (app.js) is a FrameSource; this one is a *document*
// source. It owns no logic beyond plumbing: every utterance goes to /tutor/say and
// the backend's rule-based router (core/bitgil_core/tutor.py) decides what it means,
// so the quick buttons, the typed input and the microphone cannot drift apart from
// each other — they all send the same Korean phrases a user would say.
//
// Two rules this UI must not break:
//   1. Say WHICH kind of sentence this is. `grounded` from the server is rendered as
//      원문 / 모델 and spoken in the announcement, because the two sound identical in
//      a screen reader's voice but carry completely different trust.
//   2. Never let an error be silent. Everything reaches the aria-live status line and
//      the speech queue — a blind user cannot see a red box.

const $ = (id) => document.getElementById(id);

let speaking = true;      // mirrors the 낭독 checkbox
let busy = false;         // one request at a time; the input is disabled meanwhile
let recognition = null;   // Web Speech recognition, when the browser has it

function setStatus(msg) {
	$("status").textContent = msg;
}

// 지금 보고 있는 문항. 서버가 매 응답에 실어 주는 current를 반영합니다 — 대화 기록이
// 길어져도 "내가 지금 몇 번에 있는지"는 한 곳에서 계속 보이고, 스크린리더로도 읽힙니다.
function setWhere(current) {
	const el = $("where");
	if (typeof current === "number") el.textContent = "지금 " + current + "번을 보고 있습니다.";
	else if (current === null) el.textContent = "아직 문항을 고르지 않았습니다.";
}

// ---- 낭독 -------------------------------------------------------------------

function utter(text) {
	const u = new SpeechSynthesisUtterance(text);
	u.lang = "ko-KR";
	const ko = speechSynthesis.getVoices().find((v) => v.lang && v.lang.startsWith("ko"));
	if (ko) u.voice = ko;
	speechSynthesis.speak(u);
}

// A reply always answers something the user just asked, so it cuts in — queueing
// would make them wait through the previous answer to hear the one they asked for.
function speak(text) {
	if (!speaking || !("speechSynthesis" in window) || !text) return;
	speechSynthesis.cancel();
	for (const part of text.split("\n")) {
		if (part.trim()) utter(part.trim());
	}
}

function stopSpeech() {
	if ("speechSynthesis" in window) speechSynthesis.cancel();
}

// ---- 기록 렌더링 -------------------------------------------------------------

function addUser(text) {
	const li = document.createElement("li");
	li.className = "msg user";
	li.innerHTML = '<span class="who">나</span> ';
	li.appendChild(document.createTextNode(text));
	$("log").appendChild(li);
	li.scrollIntoView({ block: "nearest" });
}

// `data` is the /tutor/* JSON: {text, grounded, unsupported, elapsed}.
function addReply(data) {
	const li = document.createElement("li");
	li.className = "msg bot" + (data.grounded ? " grounded" : "");
	const tag = document.createElement("span");
	tag.className = "tag " + (data.grounded ? "source" : "model");
	// 화면에는 짧게, 스크린리더에는 무엇을 뜻하는지 풀어서.
	tag.textContent = data.grounded ? "원문" : "모델";
	tag.setAttribute(
		"aria-label",
		data.grounded ? "시험지 원문입니다" : "모델이 한 말입니다",
	);
	li.appendChild(tag);
	if (typeof data.elapsed === "number") {
		const t = document.createElement("span");
		t.className = "elapsed";
		t.textContent = data.elapsed.toFixed(1) + "초";
		li.appendChild(t);
	}
	const body = document.createElement("p");
	body.className = "body";
	body.textContent = data.text;   // 줄바꿈은 CSS(white-space)로 살립니다
	li.appendChild(body);
	if (data.unsupported && data.unsupported.length) {
		const note = document.createElement("p");
		note.className = "notice";
		note.textContent = "원문에서 확인되지 않은 숫자: " + data.unsupported.join(", ");
		li.appendChild(note);
	}
	$("log").appendChild(li);
	li.scrollIntoView({ block: "nearest" });
}

// 모델의 말인지 원문인지를 **음성에도** 붙입니다 — 화면의 꼬리표를 못 보는 사용자에게는
// 이 접두어가 유일한 구분입니다.
function announce(data) {
	const prefix = data.grounded ? "시험지 원문. " : "모델의 설명. ";
	speak(prefix + data.text);
}

// ---- 서버 ------------------------------------------------------------------

function setEnabled(on) {
	for (const el of [$("ask"), $("send"), $("close"), $("review")]) el.disabled = !on;
	for (const b of document.querySelectorAll(".q")) b.disabled = !on;
	$("mic").disabled = !on || !recognition;
}

async function say(text) {
	const utterance = (text || "").trim();
	if (!utterance || busy) return;
	addUser(utterance);
	busy = true;
	$("send").disabled = true;
	setStatus("생각 중…");
	try {
		const res = await fetch("/tutor/say", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ text: utterance }),
		});
		const data = await res.json();
		if (!res.ok) {
			const msg = data.text || data.error || "요청을 처리하지 못했습니다.";
			setStatus(msg);
			speak(msg);
			return;
		}
		addReply(data);
		announce(data);
		if ("current" in data) setWhere(data.current);
		setStatus(
			data.grounded
				? "시험지 원문을 읽었습니다. 다음에 무엇을 들을까요?"
				: "모델의 설명입니다. 다음에 무엇을 들을까요?",
		);
	} catch (e) {
		const msg = "백엔드 통신 오류: " + e.message;
		setStatus(msg);
		speak(msg);
	} finally {
		busy = false;
		$("send").disabled = false;
		$("ask").value = "";
		$("ask").focus();   // 다음 말을 바로 할 수 있게 초점을 되돌립니다
	}
}

function renderJumps(numbers) {
	const box = $("jump");
	box.innerHTML = "";
	if (!numbers || !numbers.length) return;
	for (const n of numbers) {
		const b = document.createElement("button");
		b.type = "button";
		b.className = "chip";
		b.textContent = n + "번";
		b.setAttribute("aria-label", n + "번 문제 읽기");
		b.addEventListener("click", () => say(n + "번 읽어줘"));
		box.appendChild(b);
	}
}

async function openPdf(file) {
	if (!file) return;
	setStatus(file.name + " 을(를) 여는 중…");
	try {
		const res = await fetch("/tutor/open?name=" + encodeURIComponent(file.name), {
			method: "POST",
			headers: { "Content-Type": "application/pdf" },
			body: file,
		});
		const data = await res.json();
		if (!res.ok) {
			// 거절 사유(스캔 PDF·형식)는 조치 가능한 한 문장이므로 그대로 읽어 줍니다.
			const msg = data.text || data.error || "시험지를 열지 못했습니다.";
			setStatus(msg);
			speak(msg);
			setEnabled(false);
			return;
		}
		$("log").innerHTML = "";
		$("doc").textContent =
			`${data.name} · ${data.pages}쪽 · 문항 ${data.questions.length}개` +
			(data.figures.length ? ` · 도표 문항 ${data.figures.join(", ")}번` : "");
		renderJumps(data.questions);
		setEnabled(true);
		addReply(data);
		announce(data);
		setWhere(null);   // 개요만 들은 상태 — 아직 문항을 고르지 않았습니다.
		setStatus("시험지를 열었습니다. 어디부터 읽을까요? '시작'이라고 하면 1번부터 함께 봅니다.");
		$("ask").focus();
	} catch (e) {
		const msg = "업로드 실패: " + e.message;
		setStatus(msg);
		speak(msg);
	}
}

// 복습 노트는 링크가 아니라 이 함수로 내려받습니다. `<a href="/tutor/review">`는 실패했을 때
// 브라우저가 JSON 응답을 그냥 띄워 버리고, 성공했을 때도 아무 말이 없습니다 — 화면을 못 보는
// 사용자에게는 저장이 됐는지조차 알 수 없는 동작입니다. 성공·실패를 **둘 다 말합니다.**
async function saveReview() {
	setStatus("복습 노트를 만드는 중…");
	try {
		const res = await fetch("/tutor/review");
		if (!res.ok) {
			const data = await res.json().catch(() => ({}));
			const msg = data.text || "복습 노트를 저장할 수 없습니다.";
			setStatus(msg);
			speak(msg);
			return;
		}
		const url = URL.createObjectURL(await res.blob());
		const a = document.createElement("a");
		a.href = url;
		a.download = "bitgil-review.md";
		a.click();
		URL.revokeObjectURL(url);
		const msg = "복습 노트를 bitgil-review.md 파일로 저장했습니다. 기계가 만든 설명이라는 고지가 함께 들어 있습니다.";
		setStatus(msg);
		speak(msg);
	} catch (e) {
		const msg = "복습 노트 저장 실패: " + e.message;
		setStatus(msg);
		speak(msg);
	}
}

async function closeDoc() {
	await fetch("/tutor/close", { method: "POST" });
	setEnabled(false);
	renderJumps([]);
	$("doc").textContent = "";
	$("where").textContent = "";
	stopSpeech();
	setStatus("시험지를 닫았습니다. 업로드본은 서버에서 삭제했습니다.");
	$("file").value = "";
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
		say(heard);
	});
	recognition.addEventListener("error", (ev) => {
		setStatus("음성 인식 오류: " + ev.error + ". 입력창에 타자로 말해도 됩니다.");
	});
	recognition.addEventListener("end", () => $("mic").setAttribute("aria-pressed", "false"));
	$("mic").addEventListener("click", () => {
		// 낭독 중에 마이크를 켜면 자기 목소리를 다시 듣습니다.
		stopSpeech();
		try {
			recognition.start();
			$("mic").setAttribute("aria-pressed", "true");
			setStatus("듣고 있습니다. 말씀하세요.");
		} catch (e) {
			setStatus("음성 인식을 시작할 수 없습니다: " + e.message);
		}
	});
}

// ---- 배선 ------------------------------------------------------------------

$("file").addEventListener("change", (e) => openPdf(e.target.files[0]));

const drop = $("drop");
for (const type of ["dragenter", "dragover"]) {
	drop.addEventListener(type, (e) => {
		e.preventDefault();
		drop.classList.add("over");
	});
}
for (const type of ["dragleave", "drop"]) {
	drop.addEventListener(type, () => drop.classList.remove("over"));
}
drop.addEventListener("drop", (e) => {
	e.preventDefault();
	openPdf(e.dataTransfer.files[0]);
});

$("askForm").addEventListener("submit", (e) => {
	e.preventDefault();
	say($("ask").value);
});

for (const b of document.querySelectorAll(".q")) {
	b.addEventListener("click", () => say(b.dataset.say));
}

$("speakOn").addEventListener("change", () => {
	speaking = $("speakOn").checked;
	if (!speaking) stopSpeech();
});
$("stopSpeech").addEventListener("click", stopSpeech);
$("review").addEventListener("click", saveReview);
$("close").addEventListener("click", closeDoc);

document.addEventListener("keydown", (e) => {
	if (e.key === "Escape") { stopSpeech(); return; }
	if (!e.altKey) return;
	const key = e.key.toLowerCase();
	const shortcuts = { n: "다음 문제", p: "이전 문제", r: "다시" };
	if (key === "m") { e.preventDefault(); $("mic").click(); return; }
	if (shortcuts[key] && !$("ask").disabled) {
		e.preventDefault();
		say(shortcuts[key]);
	}
});

fetch("/config")
	.then((r) => r.json())
	.then((cfg) => {
		$("meta").textContent =
			`프로바이더: ${cfg.provider} · 도표 설명 프로파일: ${cfg.tutor_profile}`;
		if (cfg.provider === "demo") {
			$("meta").textContent +=
				" · (데모 프로바이더 — 원문 낭독은 진짜, 도표 설명은 캔에 담긴 문장입니다)";
		}
	})
	.catch(() => setStatus("백엔드에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요."));

setupMic();
setEnabled(false);
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
