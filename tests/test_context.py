"""Tests for SessionContext (bitgil_core.context) — the recap the model sees.

Offline: no provider needed, we inspect the assembled Message list directly.
"""

from bitgil_core.context import SessionContext


def test_empty_narration_is_not_recorded():
	# A blank/whitespace-only stream must not push an empty recap bullet.
	ctx = SessionContext(system_prompt="sys")
	ctx.record_narration("")
	ctx.record_narration("   \n\t ")
	assert ctx.recent() == []


def test_recap_orders_most_recent_first_matching_label():
	# The recap is labelled "최근순" (most-recent-first); the deque stores in
	# chronological order, so the rendered list must be reversed to match.
	ctx = SessionContext(system_prompt="sys")
	ctx.record_narration("첫째")
	ctx.record_narration("둘째")
	ctx.record_narration("셋째")
	msgs = ctx.build_messages(frame=b"img")
	recap = next(m for m in msgs if "최근순" in m.text)
	# Newest bullet appears before older ones.
	assert recap.text.index("셋째") < recap.text.index("둘째") < recap.text.index("첫째")


def test_history_capped_at_size():
	ctx = SessionContext(system_prompt="sys", history_size=2)
	ctx.record_narration("a")
	ctx.record_narration("b")
	ctx.record_narration("c")
	assert ctx.recent() == ["b", "c"]


def test_no_recap_message_when_history_empty():
	ctx = SessionContext(system_prompt="sys")
	msgs = ctx.build_messages(frame=b"img")
	assert not any("최근순" in m.text for m in msgs)
	# System prompt + the user/frame message only.
	assert msgs[0].text == "sys"
