"""Deterministic safety heuristics — defense in depth for interruption triage.

The LLM classifies events (bitgil_core.triage), but we must not rely on it alone
for the highest-stakes calls: mistaking a scam for a benign notification, or
missing a security prompt. These cheap keyword heuristics run AFTER the model and
can only *raise* the alarm, never lower it — so even a wrong or unparseable model
reply still gets caught by the obvious signals. Pure and offline-testable.

Keyword lists are intentionally conservative (favour false alarms over misses)
and Korean-first, matching the profiles' target language.
"""

from __future__ import annotations

# Fake-antivirus / phishing / prize-bait phrasing. Blind users are actively
# targeted by these, so surfacing a warning is high value even if occasionally
# over-eager.
_SCAM_SIGNALS = (
	"무료 백신",
	"바이러스 감지",
	"바이러스가 감지",
	"악성코드 감지",
	"당첨",
	"경품",
	"축하합니다",
	"지금 클릭",
	"즉시 클릭",
	"여기를 클릭",
	"계정이 정지",
	"결제 정보를 확인",
	"무료로 설치",
	"claim your prize",
	"you have won",
	"virus detected",
)

# System / permission / credential prompts — never auto-act on these.
_SECURITY_SIGNALS = (
	"권한을 허용",
	"액세스를 허용",
	"접근하도록 허용",
	"관리자 권한",
	"사용자 계정 컨트롤",
	"비밀번호를 입력",
	"로그인",
	"administrator",
	"user account control",
	"uac",
	"grant access",
	"sign in",
)


def _hit(text: str, needles: tuple) -> bool:
	low = text.lower()
	return any(n.lower() in low for n in needles)


def scam_signals(text: str) -> bool:
	return _hit(text, _SCAM_SIGNALS)


def security_signals(text: str) -> bool:
	return _hit(text, _SECURITY_SIGNALS)


def augment(classification, event) -> None:
	"""Raise scam / security flags on the classification from obvious signals.

	Mutates `classification` in place. Only ever sets flags True — it cannot
	downgrade a flag the model already raised.
	"""
	text = f"{event.title} {event.text}"
	if scam_signals(text):
		classification.is_suspected_scam = True
	if security_signals(text):
		classification.is_security_prompt = True
