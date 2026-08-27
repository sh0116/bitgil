"""Tests for 수치 대조 — 해설의 숫자가 원문에 인쇄되어 있는지 확인하는 백스톱."""

from bitgil_core.factcheck import annotate_unsupported, numbers_in, unsupported_numbers


def test_numbers_in_keeps_source_spelling():
	assert numbers_in("1,200원과 3.5%, 그리고 42") == ["1,200", "3.5", "42"]


def test_numbers_in_empty_text():
	assert numbers_in("") == []


def test_supported_numbers_produce_no_complaint():
	source = "1월 120, 2월 200, 3월 90, 4월 260"
	assert unsupported_numbers("가장 높은 값은 260입니다.", [source]) == []


def test_fabricated_number_is_caught():
	# 라벨이 없는 막대의 높이를 눈금에서 보간해 "155"라고 말하는 것이 정확히 막으려는 것.
	source = "1월 120, 2월 200"
	assert unsupported_numbers("세 번째 막대는 155로 보입니다.", [source]) == ["155"]


def test_navigation_numbers_are_not_checked():
	# "1번 선택지", "2쪽"의 번호는 낭독을 위해 우리가 붙인 것이라 원문에 없는 게 당연하다.
	# 이걸 고지하면 정작 지어낸 값이 소음에 묻힌다.
	assert unsupported_numbers("2쪽 3번 문제의 1번 선택지입니다.", ["문항"]) == []


def test_a_fabricated_value_still_surfaces_next_to_navigation_numbers():
	assert unsupported_numbers("3번 문제의 답은 155입니다.", ["문항"]) == ["155"]


def test_list_markers_in_the_model_reply_are_not_checked():
	# 실측에서 나온 오탐: 모델이 답을 "1) … 5) 전반적인 추세"로 구조화하자 5가 근거 없는
	# 숫자로 고지됐다. 목록 번호는 화면에 대한 주장이 아니다.
	narration = "1) 축 정보\n2) 값\n3) 최고점\n4) 최저점\n5) 전반적인 추세"
	assert unsupported_numbers(narration, ["1월 120 2월 200"]) == []


def test_dashed_and_dotted_list_markers_are_also_skipped():
	assert unsupported_numbers("- 7) 첫째\n8. 둘째", ["문항"]) == []


def test_a_fabricated_value_after_a_list_marker_still_surfaces():
	# 목록 번호만 빼고 그 줄의 나머지는 그대로 검사한다 — 목록 안에 지어낸 값이 온다.
	assert unsupported_numbers("1) 라벨 없는 막대는 155입니다.", ["120"]) == ["155"]


def test_thousands_separator_matches_plain_digits():
	# 원문 "1200"과 해설 "1,200"은 같은 값 — 표기 차이로 오탐하면 고지가 소음이 된다.
	assert unsupported_numbers("매출은 1,200입니다.", ["매출 1200"]) == []


def test_trailing_zero_decimal_matches_integer():
	assert unsupported_numbers("값은 12.0입니다.", ["12개"]) == []


def test_percent_sign_is_not_part_of_the_value():
	assert unsupported_numbers("30% 증가", ["30 증가"]) == []


def test_multiple_sources_are_all_credited():
	# 축 라벨은 문항 밖에 인쇄될 수 있으므로 근거는 여러 곳에서 모은다.
	assert unsupported_numbers("120과 260", ["문항 120", "축 라벨 260"]) == []


def test_repeated_fabrication_is_reported_once():
	assert unsupported_numbers("155, 그리고 다시 155", ["120"]) == ["155"]


def test_annotate_leaves_clean_narration_untouched():
	text, missing = annotate_unsupported("최고점은 260입니다.", ["260"])
	assert text == "최고점은 260입니다."
	assert missing == []


def test_annotate_appends_actionable_korean_notice():
	text, missing = annotate_unsupported("최고점은 155입니다.", ["120"])
	assert missing == ["155"]
	assert "155" in text
	assert "확인되지 않은 숫자" in text
	assert "라벨을 직접 확인" in text          # 조치할 수 있는 문장이어야 한다
	assert text.startswith("최고점은 155입니다.")  # 원래 해설을 지우지 않는다


def test_annotate_with_no_sources_flags_every_number():
	_, missing = annotate_unsupported("1과 2", [])
	assert missing == ["1", "2"]
