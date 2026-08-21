"""Tests for the interruption-triage core (bitgil_core.triage).

Two layers, both offline:
  - apply_policy(): the deterministic safety guardrails — no LLM.
  - InterruptTriage.triage(): classification + policy, with a fake provider.
"""

import json

from bitgil_core.providers.base import VisionProvider, VisionResponse
from bitgil_core.triage import (
	INTERRUPT,
	QUEUE,
	SUPPRESS,
	DesktopEvent,
	EventClassification,
	InterruptTriage,
	apply_policy,
)


def _cls(**kw) -> EventClassification:
	base = dict(category="notification", urgency="low", summary="요약")
	base.update(kw)
	return EventClassification(**base)


class JsonProvider(VisionProvider):
	"""Returns a canned classification JSON, records the messages it saw."""

	name = "json-fake"

	def __init__(self, payload):
		self.payload = payload
		self.last_messages = None

	def complete(self, messages, *, max_tokens=300):
		self.last_messages = list(messages)
		text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
		return VisionResponse(text=text)


# --- apply_policy: safety guardrails ----------------------------------------

def test_security_prompt_always_interrupts_and_needs_confirmation():
	# Even at low urgency, a security/permission prompt must be surfaced and
	# flagged so the copilot never clicks it unprompted.
	d = apply_policy(_cls(urgency="low", is_security_prompt=True), DesktopEvent(kind="permission"))
	assert d.action == INTERRUPT
	assert d.needs_confirmation is True
	assert d.reason == "security-prompt"


def test_suspected_scam_interrupts_with_warning():
	d = apply_policy(_cls(urgency="low", is_suspected_scam=True, summary="무료 상품 당첨"), DesktopEvent())
	assert d.action == INTERRUPT
	assert "사기" in d.spoken  # explicit warning prepended
	assert d.reason == "suspected-scam"
	# A scam popup is the single worst place for an unattended proxy click, so it
	# must gate confirmation just like a security prompt. This assertion was the
	# missing coverage that let the flag regress.
	assert d.needs_confirmation is True


def test_suspected_scam_takes_priority_over_security_flag():
	# When both fire, the scam warning wins the ordering, and confirmation is
	# still required either way.
	d = apply_policy(
		_cls(urgency="high", is_suspected_scam=True, is_security_prompt=True),
		DesktopEvent(kind="dialog"),
	)
	assert d.reason == "suspected-scam"
	assert d.needs_confirmation is True


def test_low_urgency_irrelevant_notification_is_suppressed():
	d = apply_policy(_cls(urgency="low", relevant_to_goal=False), DesktopEvent(kind="notification"))
	assert d.action == SUPPRESS
	assert d.spoken == ""


def test_medium_urgency_is_queued_not_interrupted():
	d = apply_policy(_cls(urgency="medium"), DesktopEvent())
	assert d.action == QUEUE


def test_high_urgency_interrupts():
	d = apply_policy(_cls(urgency="high"), DesktopEvent())
	assert d.action == INTERRUPT


def test_needs_user_decision_interrupts():
	d = apply_policy(_cls(urgency="low", suggested_action="needs_user_decision"), DesktopEvent())
	assert d.action == INTERRUPT


def test_relevant_to_goal_is_queued():
	d = apply_policy(_cls(urgency="low", relevant_to_goal=True), DesktopEvent())
	assert d.action == QUEUE


def test_focus_stealing_low_value_is_queued_not_dropped():
	# Something grabbed the foreground: context changed, so don't silently drop it.
	d = apply_policy(_cls(urgency="low", relevant_to_goal=False), DesktopEvent(stole_focus=True))
	assert d.action == QUEUE


def test_focus_stealing_modal_interrupts():
	d = apply_policy(
		_cls(urgency="low", category="modal_dialog"),
		DesktopEvent(kind="dialog", stole_focus=True),
	)
	assert d.action == INTERRUPT


def test_focus_stealing_permission_request_needs_confirmation():
	# A permission_request that grabbed focus interrupts via rule 3 even if the
	# model failed to set is_security_prompt — and because it's security-sensitive,
	# it must still gate confirmation so the copilot never auto-clicks it.
	d = apply_policy(
		_cls(urgency="low", category="permission_request", is_security_prompt=False),
		DesktopEvent(kind="permission", stole_focus=True),
	)
	assert d.action == INTERRUPT
	assert d.needs_confirmation is True


def test_focus_stealing_plain_modal_does_not_force_confirmation():
	# A non-security modal (e.g. an app dialog) interrupts but should not claim to
	# need confirmation — that flag is reserved for security/scam decisions.
	d = apply_policy(
		_cls(urgency="low", category="modal_dialog"),
		DesktopEvent(kind="dialog", stole_focus=True),
	)
	assert d.action == INTERRUPT
	assert d.needs_confirmation is False


def test_unrecognized_urgency_is_queued_not_suppressed():
	# A non-canonical urgency ("critical") must never fall through to a silent
	# drop — an important event with an off-schema label is surfaced, queued.
	d = apply_policy(
		_cls(urgency="critical", relevant_to_goal=False),
		DesktopEvent(kind="error", text="디스크 오류"),
	)
	assert d.action == QUEUE
	assert d.reason == "queue-unrecognized-urgency"
	assert d.spoken  # not silence


def test_only_explicit_low_urgency_is_suppressed():
	d = apply_policy(_cls(urgency="low", relevant_to_goal=False), DesktopEvent(kind="notification"))
	assert d.action == SUPPRESS


def test_interrupt_uses_event_fallback_when_summary_missing():
	# Rules 3/4 must not speak an empty string when the model gave no summary —
	# fall back to the event's own text so the user always hears something.
	d = apply_policy(
		_cls(urgency="high", summary=""),
		DesktopEvent(kind="error", text="업데이트 실패"),
	)
	assert d.action == INTERRUPT
	assert d.spoken == "업데이트 실패"


# --- InterruptTriage: classification + policy -------------------------------

def test_triage_parses_json_and_applies_policy():
	provider = JsonProvider(
		{
			"category": "permission_request",
			"urgency": "high",
			"is_security_prompt": True,
			"summary": "이 앱이 카메라 접근 권한을 요청합니다.",
			"suggested_action": "needs_user_decision",
		}
	)
	triage = InterruptTriage(provider)
	d = triage.triage(
		DesktopEvent(kind="permission", source_app="Zoom", text="Allow camera access?"),
		user_goal="화상 회의 참여",
	)
	assert d.action == INTERRUPT
	assert d.needs_confirmation is True
	assert "카메라" in d.spoken
	# the goal should reach the model
	assert any("화상 회의 참여" in m.text for m in provider.last_messages)


def test_triage_handles_code_fenced_json():
	provider = JsonProvider('```json\n{"category":"ad","urgency":"low"}\n```')
	d = InterruptTriage(provider).triage(DesktopEvent(kind="notification", title="광고"))
	assert d.action == SUPPRESS


def test_triage_unparseable_reply_queues_raw_text_not_silence():
	provider = JsonProvider("모델이 JSON을 안 줬어요")
	d = InterruptTriage(provider).triage(
		DesktopEvent(kind="unknown", text="갑자기 뜬 창")
	)
	assert d.action == QUEUE          # never silently dropped
	assert d.spoken == "갑자기 뜬 창"  # falls back to the event's own text
	assert d.reason == "unparsed-classification"
