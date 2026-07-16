from __future__ import annotations


EXCHANGE_NAMES = {"sh": "上海", "sz": "深圳", "bj": "北京"}


class SecurityIdentityError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_security_code(code: str) -> str:
    normalized = str(code).strip()
    if not normalized.isdigit() or len(normalized) > 6:
        raise SecurityIdentityError("INVALID_SECURITY_CODE", "证券代码必须是六位数字")
    return normalized.zfill(6)


def infer_exchange(code: str) -> str:
    normalized = normalize_security_code(code)
    if normalized.startswith(("4", "8", "9")):
        return "bj"
    if normalized.startswith(("5", "6")):
        return "sh"
    return "sz"


def validate_security_identity(exchange: str, code: str) -> tuple[str, str]:
    normalized_exchange = str(exchange).strip().lower()
    normalized_code = normalize_security_code(code)
    inferred = infer_exchange(normalized_code)
    if normalized_exchange != inferred:
        expected = EXCHANGE_NAMES.get(inferred, inferred)
        actual = EXCHANGE_NAMES.get(normalized_exchange, normalized_exchange or "空")
        raise SecurityIdentityError(
            "SECURITY_IDENTITY_MISMATCH",
            f"证券代码 {normalized_code} 属于{expected}市场，不能按{actual}市场查询",
        )
    return normalized_exchange, normalized_code


def is_security_identity_valid(exchange: str, code: str) -> bool:
    try:
        validate_security_identity(exchange, code)
    except SecurityIdentityError:
        return False
    return True
