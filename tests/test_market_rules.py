from datetime import date

from kline.p1.market_rules import SecurityStatus, is_no_limit_session, status_from_name


def test_registration_ipo_first_five_sessions_are_no_limit():
    listing = date(2024, 1, 2)
    assert is_no_limit_session("sh", "688001", listing, 0, listing) is True
    assert is_no_limit_session("sh", "688001", listing, 4, date(2024, 1, 8)) is True
    assert is_no_limit_session("sh", "688001", listing, 5, date(2024, 1, 9)) is False


def test_legacy_main_board_ipo_is_not_treated_as_no_limit():
    listing = date(2020, 1, 2)
    assert is_no_limit_session("sh", "600001", listing, 0, listing) is False


def test_name_status_marks_st_and_records_approximation():
    status = status_from_name("*ST 示例")
    assert status == SecurityStatus(is_st=True, is_approx=True, reason="current-name approximation")
