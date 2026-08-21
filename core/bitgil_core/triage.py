"""InterruptTriage — decide whether a desktop event deserves the user's ear.

Part of the ambient-copilot direction (docs/ambient-copilot.md, roadmap M6). A
screen reader reads every popup literally and linearly; for an unfamiliar user —
especially a blind child — a sudden antivirus or update notification arrives with
no context about where it came from, whether it matters, or what to do.

This module is the "interruption triage" core: given a structured desktop event
(and optionally what the user is currently trying to do), it classifies the event
with the LLM and then applies a DETERMINISTIC safety policy to decide the output
action — interrupt / queue / suppress — plus what to actually say.

Screen-reader-agnostic and offline-testable, like the rest of bitgil_core:
  - `apply_policy()` is a pure function (no LLM). The safety guardrails live here,
    so they can be unit-tested exhaustively without a model in the loop.
  - `InterruptTriage.triage()` adds the LLM classification on top and takes an
    injected VisionProvider, so tests use a fake.

The three actions map onto the addon's SpeechBridge policy: interrupt = cut in,
queue = speak after the current utterance, suppress = log only (stay silent).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

from . import safety
from .providers.base import Message, VisionProvider

# Output actions (map onto SpeechBridge queue/interrupt/defer).
INTERRUPT = "interrupt"
QUEUE = "queue"
SUPPRESS = "suppress"


@dataclass
class DesktopEvent:
	"""A structured thing that appeared on screen — from an OS event source.

	Populated by the platform adapter (UI Automation / toast listener / process
	watch on Windows), NOT from pixels. Vision is only a fallback when these
	structured fields are too thin to classify.
	"""

	kind: str = "unknown"       # notification | dialog | permission | error | unknown
	source_app: str = ""         # process / app the event came from, if known
	title: str = ""
	text: str = ""
	stole_focus: bool = False    # did it grab the foreground / interrupt the user


@dataclass
class EventClassification:
	"""The LLM's read of an event. Advisory — apply_policy() has final say."""

	category: str = "unknown"          # notification | modal_dialog | permission_request | error | ad | system
	urgency: str = "medium"            # low | medium | high
	relevant_to_goal: bool = False
	is_security_prompt: bool = False   # UAC / permission / login — never auto-act
	is_suspected_scam: bool = False    # fake antivirus / phishing popup
	summary: str = ""                  # short, contextual, what to tell the user
	suggested_action: str = "informational"  # informational | needs_user_decision | dismissible


@dataclass
class TriageDecision:
	action: str                  # INTERRUPT | QUEUE | SUPPRESS
	spoken: str = ""             # what to say now ("" when suppressed)
	category: str = "unknown"
	urgency: str = "medium"
	needs_confirmation: bool = False  # any proxy action on this must be confirmed first
	reason: str = ""             # why this decision — for tuning / logging


def apply_policy(cls: EventClassification, event: DesktopEvent) -> TriageDecision:
	"""Turn an (advisory) classification into a decision under safety guardrails.

	Pure and deterministic — this is where the "never silently drop a security
	prompt", "always warn on a suspected scam", "never auto-confirm" rules live.
	Ordered by priority; the first matching rule wins.
	"""
	# 1. Suspected scam — always surface, loudly, with an explicit warning, and
	#    flag that any action on it must be user-confirmed. A phishing/fake-AV
	#    popup is exactly where an unattended proxy click does the most harm, so
	#    needs_confirmation must be set here just as it is for security prompts.
	if cls.is_suspected_scam:
		warn = "주의: 사기(스캠)로 의심되는 창입니다. " + (cls.summary or _fallback_text(event))
		return TriageDecision(
			INTERRUPT, warn, cls.category, "high",
			needs_confirmation=True, reason="suspected-scam",
		)

	# 2. Security / permission prompt — always surface, and flag that any action
	#    on it must be user-confirmed (the copilot never clicks these itself).
	if cls.is_security_prompt:
		return TriageDecision(
			INTERRUPT, cls.summary or _fallback_text(event), cls.category, "high",
			needs_confirmation=True, reason="security-prompt",
		)

	# 3. Demands attention now: high urgency, a decision is required, or a modal
	#    dialog grabbed focus and blocks what the user was doing.
	if (
		cls.urgency == "high"
		or cls.suggested_action == "needs_user_decision"
		or (event.stole_focus and cls.category in ("modal_dialog", "permission_request"))
	):
		# A permission_request is inherently security-sensitive: even if the model
		# didn't set is_security_prompt (a miss), the copilot must never auto-act on
		# it — carry the confirmation flag through this branch too.
		needs_conf = cls.category == "permission_request"
		return TriageDecision(
			INTERRUPT, cls.summary or _fallback_text(event), cls.category, cls.urgency,
			needs_confirmation=needs_conf, reason="attention-now",
		)

	# 4. Worth mentioning, but not worth cutting in: relevant to the current
	#    goal, medium urgency, or it stole focus (context changed — don't drop).
	if cls.relevant_to_goal or cls.urgency == "medium" or event.stole_focus:
		return TriageDecision(
			QUEUE, cls.summary or _fallback_text(event), cls.category, cls.urgency, reason="queue"
		)

	# 5. Only an explicitly LOW-urgency, irrelevant event is dropped (ads,
	#    background chatter). An unrecognized urgency value ("critical", "urgent",
	#    …) must NOT be silently suppressed — surface it, queued.
	if cls.urgency == "low":
		return TriageDecision(SUPPRESS, "", cls.category, cls.urgency, reason="low-value")
	return TriageDecision(
		QUEUE, cls.summary or _fallback_text(event), cls.category, cls.urgency,
		reason="queue-unrecognized-urgency",
	)


_SYSTEM_PROMPT = """당신은 시각장애인 사용자의 데스크톱 코파일럿입니다. 화면에 방금 나타난
창/알림을 분류하세요. 사용자는 화면을 볼 수 없으므로, 이것이 무엇이고 왜 떴는지 맥락을
파악해야 합니다.

반드시 아래 스키마의 JSON 하나만 출력하세요(설명·코드펜스 금지):
{
  "category": "notification|modal_dialog|permission_request|error|ad|system",
  "urgency": "low|medium|high",
  "relevant_to_goal": true|false,
  "is_security_prompt": true|false,
  "is_suspected_scam": true|false,
  "summary": "사용자에게 들려줄 짧고 친절한 한국어 설명",
  "suggested_action": "informational|needs_user_decision|dismissible"
}

원칙:
- 권한 요청·UAC·로그인·결제 등 보안 관련이면 is_security_prompt=true.
- 가짜 백신 경고, 당첨/피싱 등 사기 의심이면 is_suspected_scam=true.
- 확실하지 않으면 지어내지 말고 urgency는 medium으로 두세요."""


class InterruptTriage:
	def __init__(self, provider: VisionProvider, max_tokens: int = 240):
		self.provider = provider
		self.max_tokens = max_tokens

	def triage(self, event: DesktopEvent, user_goal: str = "") -> TriageDecision:
		"""Classify an event with the LLM, then decide under the safety policy."""
		messages = self._build_messages(event, user_goal)
		resp = self.provider.complete(messages, max_tokens=self.max_tokens)
		cls = _parse_classification(resp.text)
		if cls is None:
			# Model reply was unusable. Still let deterministic safety heuristics
			# catch obvious scams / security prompts before falling back.
			probe = EventClassification(
				category="unknown", urgency="medium", summary=_fallback_text(event)
			)
			safety.augment(probe, event)
			if probe.is_suspected_scam or probe.is_security_prompt:
				return apply_policy(probe, event)
			# Never drop an event we couldn't classify — surface it, queued.
			return TriageDecision(
				QUEUE, _fallback_text(event), "unknown", "medium",
				reason="unparsed-classification",
			)
		if not cls.summary:
			cls.summary = _fallback_text(event)
		# Defense in depth: heuristics can only raise the alarm, never lower it.
		safety.augment(cls, event)
		return apply_policy(cls, event)

	def _build_messages(self, event: DesktopEvent, user_goal: str) -> List[Message]:
		lines = [
			f"이벤트 종류: {event.kind}",
			f"출처 앱: {event.source_app or '알 수 없음'}",
			f"포커스를 가져감: {'예' if event.stole_focus else '아니오'}",
			f"제목: {event.title}",
			f"내용: {event.text}",
		]
		if user_goal:
			lines.append(f"사용자가 지금 하려는 일: {user_goal}")
		return [
			Message(role="system", text=_SYSTEM_PROMPT),
			Message(role="user", text="\n".join(lines)),
		]


def _fallback_text(event: DesktopEvent) -> str:
	return event.text or event.title or "알 수 없는 창이 나타났습니다."


def _extract_json(text: str) -> str:
	"""Pull the JSON object out of a model reply (tolerates ``` fences / prose)."""
	s = text.strip()
	if s.startswith("```"):
		s = s.strip("`")
		# drop a leading "json" language tag if present
		if s[:4].lower() == "json":
			s = s[4:]
	start = s.find("{")
	end = s.rfind("}")
	if start != -1 and end != -1 and end > start:
		return s[start : end + 1]
	return s


def _parse_classification(text: str) -> Optional[EventClassification]:
	try:
		data = json.loads(_extract_json(text))
	except (ValueError, TypeError):
		return None
	if not isinstance(data, dict):
		return None
	return EventClassification(
		category=str(data.get("category", "unknown")),
		urgency=str(data.get("urgency", "medium")),
		relevant_to_goal=bool(data.get("relevant_to_goal", False)),
		is_security_prompt=bool(data.get("is_security_prompt", False)),
		is_suspected_scam=bool(data.get("is_suspected_scam", False)),
		summary=str(data.get("summary", "")).strip(),
		suggested_action=str(data.get("suggested_action", "informational")),
	)
