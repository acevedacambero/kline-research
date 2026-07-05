from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SecurityStatus:
    is_st: bool
    is_approx: bool
    reason: str


def status_from_name(name: str) -> SecurityStatus:
    normalized = name.upper().replace(" ", "")
    is_st = normalized.startswith(("ST", "*ST"))
    return SecurityStatus(is_st, True, "current-name approximation")


def is_no_limit_session(
    exchange: str,
    code: str,
    listing_date: date,
    trading_session_index: int,
    trading_date: date,
) -> bool:
    exchange = exchange.lower()
    registration_window = (
        code.startswith(("688", "689"))
        or (code.startswith(("300", "301")) and listing_date >= date(2020, 8, 24))
        or exchange == "bj"
        or (
            exchange in {"sh", "sz"}
            and code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))
            and listing_date >= date(2023, 4, 10)
        )
    )
    return registration_window and 0 <= trading_session_index < 5
