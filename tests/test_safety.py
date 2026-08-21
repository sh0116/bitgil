"""Tests for the deterministic safety heuristics (bitgil_core.safety) and their
integration with triage (heuristics catch what the model misses)."""

from bitgil_core import safety
from bitgil_core.providers.base import VisionProvider, VisionResponse
from bitgil_core.triage import INTERRUPT, DesktopEvent, EventClassification, InterruptTriage


def test_scam_keywords_detected():
	assert safety.scam_signals("무료 백신을 지금 설치하세요")
	assert safety.scam_signals("VIRUS DETECTED! claim your prize")
	assert not safety.scam_signals("문서를 저장했습니다")


def test_security_keywords_detected():
	assert safety.security_signals("이 앱이 카메라에 접근하도록 허용하시겠습니까")
	assert safety.security_signals("User Account Control")
	assert not safety.security_signals("날씨가 맑습니다")


def test_security_keywords_cover_common_permission_phrasing():
	# Live QA found these common Korean permission phrasings slipped through the
	# heuristic (the model-less fallback path). Regression-guard each.
	assert safety.security_signals("권한 요청")
	assert safety.security_signals("카메라 접근을 허용하시겠습니까?")
	assert safety.security_signals("마이크 접근을 허용할까요")
	assert safety.security_signals("위치 정보 접근을 허용")
	assert safety.security_signals("This app wants to access your files")


def test_scam_keywords_cover_english_tech_support_scam():
	assert safety.scam_signals("Your computer is infected. Call Microsoft now.")
	assert safety.scam_signals("Call this number for tech support")


def test_triage_heuristics_catch_security_prompt_when_reply_unparseable():
	# The whole point of the fallback: an unparsed model reply must not let a
	# permission prompt through un-gated. Heuristics flag it and it interrupts
	# with confirmation required.
	provider = _JsonProvider("모델이 JSON을 주지 않음")
	d = InterruptTriage(provider).triage(
		DesktopEvent(kind="permission", title="권한 요청", text="카메라 접근을 허용하시겠습니까?")
	)
	assert d.action == INTERRUPT
	assert d.needs_confirmation is True
	assert d.reason == "security-prompt"


def test_augment_only_raises_flags():
	cls = EventClassification(is_suspected_scam=True)
	# a benign event must not clear an already-raised flag
	safety.augment(cls, DesktopEvent(text="문서 저장 완료"))
	assert cls.is_suspected_scam is True


class _JsonProvider(VisionProvider):
	name = "json"

	def __init__(self, text):
		self._text = text

	def complete(self, messages, *, max_tokens=300):
		return VisionResponse(text=self._text)


def test_triage_heuristics_catch_scam_the_model_missed():
	# Model says harmless notification; heuristics must still flag the scam.
	provider = _JsonProvider('{"category":"notification","urgency":"low","is_suspected_scam":false}')
	d = InterruptTriage(provider).triage(
		DesktopEvent(kind="dialog", text="축하합니다! 무료 백신 당첨, 지금 클릭")
	)
	assert d.action == INTERRUPT
	assert d.reason == "suspected-scam"


def test_triage_heuristics_catch_scam_even_when_reply_unparseable():
	provider = _JsonProvider("모델이 JSON을 주지 않음")
	d = InterruptTriage(provider).triage(
		DesktopEvent(kind="dialog", text="바이러스 감지! 여기를 클릭하여 무료로 설치")
	)
	assert d.action == INTERRUPT
	assert d.reason == "suspected-scam"
