import pytest

from kline.data.security_identity import (
    SecurityIdentityError,
    infer_exchange,
    is_security_identity_valid,
    normalize_security_code,
    validate_security_identity,
)


@pytest.mark.parametrize(
    ("code", "exchange"),
    [
        ("600000", "sh"),
        ("688001", "sh"),
        ("000001", "sz"),
        ("300029", "sz"),
        ("301377", "sz"),
        ("830001", "bj"),
    ],
)
def test_infer_exchange_from_security_code(code, exchange):
    assert infer_exchange(code) == exchange


def test_security_code_is_normalized_to_six_digits():
    assert normalize_security_code("1") == "000001"
    assert validate_security_identity("SZ", "1") == ("sz", "000001")


@pytest.mark.parametrize(
    ("exchange", "code", "expected"),
    [
        ("sh", "301377", "属于深圳市场"),
        ("sz", "601100", "属于上海市场"),
    ],
)
def test_validate_security_identity_rejects_market_mismatch(exchange, code, expected):
    with pytest.raises(SecurityIdentityError, match=expected) as error:
        validate_security_identity(exchange, code)
    assert error.value.code == "SECURITY_IDENTITY_MISMATCH"


@pytest.mark.parametrize("code", ["", "abc", "1234567"])
def test_validate_security_identity_rejects_invalid_code(code):
    with pytest.raises(SecurityIdentityError) as error:
        validate_security_identity("sh", code)
    assert error.value.code == "INVALID_SECURITY_CODE"


def test_is_security_identity_valid_handles_malformed_codes():
    assert is_security_identity_valid("sh", "600000") is True
    assert is_security_identity_valid("sh", "not-a-code") is False
