"""Offline tests for the guidance-first copilot scaffold (M7-a).

No LLM, no browser, no desktop — every collaborator is a fake or a pure function.
The bulk exercises the safety centerpiece: gate_action() must DEFAULT-DENY and
only open for user-initiated + reversible + tree-identified + non-sensitive
actions (docs/agent-copilot.md §C/§F).
"""

from bitgil_core.agent import (
	Action,
	Advisor,
	AdvisorLoop,
	Automator,
	IntentSession,
	Node,
	Reporter,
	gate_action,
	ground,
)
from bitgil_core.agent.grounding import TREE, VISION, Target
from bitgil_core.providers.base import Message, VisionResponse


# --- fakes -------------------------------------------------------------------

class _FakeProvider:
	name = "fake"

	def __init__(self, text="우측 상단 '로그인' 버튼입니다. Tab 3번 후 Enter로 갈 수 있어요."):
		self._text = text
		self.calls = []

	def complete(self, messages, *, max_tokens=300):
		self.calls.append(messages)
		return VisionResponse(text=self._text)

	def stream(self, messages, *, max_tokens=300):
		yield self._text


class _FakeChangeResult:
	def __init__(self, changed, reason):
		self.changed = changed
		self.reason = reason


class _FakeDetector:
	def __init__(self, changed=True, reason="phash"):
		self._r = _FakeChangeResult(changed, reason)

	def evaluate(self, frame):
		return self._r


class _FakeEngine:
	def __init__(self, text="로그인 화면이 나타났습니다."):
		self._text = text

	def narrate(self, frame, question=""):
		from bitgil_core.engine import Narration
		return Narration(text=self._text)


class _RecordingAutomator(Automator):
	def __init__(self):
		self.performed = []

	def perform(self, action):
		self.performed.append(action)


def _tree_target(label="스크롤"):
	return Target(label=label, source=TREE, node=Node(role="button", name=label), confidence=1.0)


# --- gate_action: default-deny + the three conditions ------------------------

def test_gate_denies_when_not_user_initiated():
	a = Action(kind="scroll", target=_tree_target(), user_initiated=False)
	r = gate_action(a)
	assert not r.allowed and r.reason == "not-user-initiated"


def test_gate_denies_irreversible_kind():
	a = Action(kind="activate", target=_tree_target(), user_initiated=True)
	r = gate_action(a)
	assert not r.allowed and r.reason.startswith("irreversible-kind")


def test_gate_denies_vision_only_target():
	# Vision-grounded target is guidance-only — never a basis for an auto-click.
	vis = Target(label="스크롤", source=VISION, confidence=0.3, hint="화면 우측 상단")
	a = Action(kind="scroll", target=vis, user_initiated=True)
	r = gate_action(a)
	assert not r.allowed and r.reason == "not-tree-identified"


def test_gate_denies_missing_target():
	a = Action(kind="scroll", target=None, user_initiated=True)
	assert not gate_action(a).allowed


def test_gate_denies_sensitive_target_even_if_reversible():
	# A reversible kind onto a "결제"/"login" labelled node is still guidance-only.
	a = Action(kind="focus", target=_tree_target("결제 확정"), user_initiated=True)
	r = gate_action(a)
	assert not r.allowed and r.reason == "sensitive-target"


def test_gate_denies_sensitive_english_description():
	a = Action(kind="scroll", target=_tree_target("항목 목록"), user_initiated=True,
	           description="submit the payment form")
	assert gate_action(a).reason == "sensitive-target"


def test_gate_allows_user_initiated_reversible_tree_target():
	a = Action(kind="scroll", target=_tree_target("다음 항목"), user_initiated=True)
	r = gate_action(a)
	assert r.allowed and r.reason == "ok" and r.fallback == ""


# --- Automator.run enforces the gate -----------------------------------------

def test_automator_run_performs_only_when_gate_allows():
	auto = _RecordingAutomator()
	denied = auto.run(Action(kind="activate", target=_tree_target(), user_initiated=True))
	assert not denied.allowed and auto.performed == []

	allowed = auto.run(Action(kind="scroll", target=_tree_target(), user_initiated=True))
	assert allowed.allowed and len(auto.performed) == 1


# --- grounding: tree-first, vision guidance-only -----------------------------

def test_ground_prefers_exact_tree_node():
	nodes = [Node(role="button", name="로그인"), Node(role="link", name="회원가입")]
	t = ground("로그인", nodes)
	assert t.source == TREE and t.tree_identified and t.confidence == 1.0


def test_ground_substring_tree_match():
	nodes = [Node(role="button", name="로그인 하기")]
	t = ground("로그인", nodes)
	assert t.source == TREE and t.confidence < 1.0


def test_ground_falls_back_to_vision_hint_only():
	t = ground("로그인", [], vision_hint="화면 우측 상단")
	assert t is not None and t.source == VISION and not t.tree_identified


def test_ground_returns_none_without_match_or_hint():
	assert ground("없는버튼", [Node(name="로그인")]) is None


# --- IntentSession: records, never auto-acts ---------------------------------

def test_intent_session_holds_goal_and_clarifies():
	s = IntentSession()
	s.set_goal("로그인하고 싶어")
	assert s.goal == "로그인하고 싶어"
	assert s.needs_clarification("어느 계정으로 로그인할까요?") is True
	s.resolve_clarification("회사 계정")
	assert "회사 계정" in s.goal and not s.needs_clarification()


# --- Advisor: builds an image message, returns visible-only guidance ---------

def test_advisor_returns_guidance_text():
	p = _FakeProvider()
	g = Advisor(p).advise(b"frame-bytes", "로그인하고 싶어")
	assert "로그인" in g.text
	# The frame must be attached to the user message as an image.
	sent = p.calls[0]
	assert any(isinstance(m, Message) and m.image == b"frame-bytes" for m in sent)


def test_advisor_grounds_named_target():
	p = _FakeProvider()
	nodes = [Node(role="button", name="로그인")]
	g = Advisor(p).advise(b"f", "로그인", nodes=nodes, named_target="로그인")
	assert g.target is not None and g.target.tree_identified


# --- Reporter: reports change, never hides no-change -------------------------

def test_reporter_describes_change():
	rep = Reporter(_FakeEngine(), _FakeDetector(changed=True))
	r = rep.report(b"f")
	assert r.changed and "로그인" in r.spoken


def test_reporter_reports_no_change_honestly():
	rep = Reporter(_FakeEngine(), _FakeDetector(changed=False, reason="no-change"))
	r = rep.report(b"f")
	assert not r.changed and r.reason == "no-change"


# --- AdvisorLoop: gate integration + barge-in --------------------------------

def _loop(automator=None, is_stop=None):
	return AdvisorLoop(
		IntentSession(),
		Advisor(_FakeProvider()),
		Reporter(_FakeEngine(), _FakeDetector(changed=True)),
		automator=automator,
		is_stop=is_stop,
	)


def test_loop_advise_uses_current_goal():
	loop = _loop()
	loop.set_goal("로그인하고 싶어")
	g = loop.advise(b"f")
	assert g.text


def test_loop_act_performs_gated_action_and_reports():
	auto = _RecordingAutomator()
	loop = _loop(automator=auto)
	loop.set_goal("스크롤")
	res = loop.act(Action(kind="scroll", target=_tree_target(), user_initiated=True), frame=b"f")
	assert res.performed and res.report and res.report.changed
	assert len(auto.performed) == 1


def test_loop_act_denied_falls_back_to_guidance():
	auto = _RecordingAutomator()
	loop = _loop(automator=auto)
	res = loop.act(Action(kind="activate", target=_tree_target(), user_initiated=True))
	assert not res.performed and auto.performed == [] and "안내" in res.spoken


def test_loop_bargein_aborts_before_perform():
	auto = _RecordingAutomator()
	loop = _loop(automator=auto)
	loop.stop()  # user said "멈춰"
	res = loop.act(Action(kind="scroll", target=_tree_target(), user_initiated=True), frame=b"f")
	assert not res.performed and auto.performed == [] and "중단" in res.spoken


def test_loop_is_stop_predicate_aborts():
	auto = _RecordingAutomator()
	loop = _loop(automator=auto, is_stop=lambda: True)
	res = loop.act(Action(kind="scroll", target=_tree_target(), user_initiated=True))
	assert not res.performed and auto.performed == []


def test_loop_new_goal_clears_prior_stop():
	auto = _RecordingAutomator()
	loop = _loop(automator=auto)
	loop.stop()
	loop.set_goal("스크롤")  # fresh goal clears the barge-in
	res = loop.act(Action(kind="scroll", target=_tree_target(), user_initiated=True), frame=b"f")
	assert res.performed
