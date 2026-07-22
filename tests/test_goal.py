"""Tests for GoalTracker (bitgil_core.goal)."""

from bitgil_core.goal import GoalTracker


def test_notes_and_context_most_recent_first():
	g = GoalTracker(window=8)
	g.note("메일 앱을 열었습니다")
	g.note("받은 편지함이 보입니다")
	ctx = g.context()
	# most recent first
	assert ctx.index("받은 편지함") < ctx.index("메일 앱")


def test_window_bounds_observations():
	g = GoalTracker(window=3)
	for i in range(5):
		g.note(f"관찰 {i}")
	obs = g.observations()
	assert len(obs) == 3
	assert obs == ["관찰 2", "관찰 3", "관찰 4"]


def test_blank_notes_ignored():
	g = GoalTracker()
	g.note("")
	g.note("   ")
	assert g.observations() == []


def test_context_char_cap():
	g = GoalTracker()
	g.note("가" * 500)
	assert len(g.context(max_chars=100)) == 100


def test_clear():
	g = GoalTracker()
	g.note("뭔가")
	g.clear()
	assert g.observations() == []
