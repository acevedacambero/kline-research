"""Versioned Shanghai/Shenzhen provider readiness gate."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from time import perf_counter
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd


GATE_VERSION = "sh-sz-provider-g2-v2"
EASTMONEY_PROVIDER = "eastmoney"
TENCENT_PROVIDER = "tencent"
SINA_PROVIDER = "sina-raw"
FACTOR_PROVIDER = "sina-factor"
INDEX_PROVIDER = "tencent-index"
CALENDAR_PROVIDER = "calendar"
CANONICAL_PROVIDERS = (
    TENCENT_PROVIDER,
    INDEX_PROVIDER,
    FACTOR_PROVIDER,
    SINA_PROVIDER,
    CALENDAR_PROVIDER,
    EASTMONEY_PROVIDER,
)
MARKET_DATA_PROVIDERS = frozenset(
    {EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER, INDEX_PROVIDER}
)
OHLCV_FIELDS = frozenset({"open", "high", "low", "close", "volume"})
REPRESENTATIVE_SECURITIES = (
    ("sh", "600000"), ("sz", "000001"), ("sh", "688981"),
    ("sz", "300750"), ("sh", "600519"), ("sz", "002594"),
    ("sh", "601318"), ("sz", "000858"), ("sh", "688036"),
    ("sz", "000333"),
)
FACTOR_SECURITIES = REPRESENTATIVE_SECURITIES[:6]
SINA_FALLBACK_SECURITIES = REPRESENTATIVE_SECURITIES[:2]
INDEX_TARGETS = (("sh", "000001"), ("sz", "399001"))

ProviderAdapter = Callable[[str, str, date, date], object]


@dataclass(frozen=True)
class ProbeObservation:
    provider: str
    security: str
    success: bool
    elapsed_seconds: float
    rows: int
    missing_fields: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None
    factor_coverage_complete: bool | None = None
    factor_values_valid: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))


@dataclass(frozen=True)
class ProviderReport:
    observations: int
    successes: int
    success_rate: float
    mean_latency_seconds: float
    p95_latency_seconds: float
    empty_response_count: int
    missing_field_count: int
    error_categories: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "error_categories", MappingProxyType(dict(self.error_categories)))


@dataclass(frozen=True)
class ProbeReport:
    providers: Mapping[str, ProviderReport]
    passed: bool
    reasons: tuple[str, ...]
    observations: tuple[ProbeObservation, ...]
    required_checks: Mapping[str, bool]
    diagnostic_checks: Mapping[str, bool]
    warnings: tuple[str, ...] = ()
    gate_version: str = GATE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))
        object.__setattr__(self, "required_checks", MappingProxyType(dict(self.required_checks)))
        object.__setattr__(self, "diagnostic_checks", MappingProxyType(dict(self.diagnostic_checks)))
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "observations", tuple(self.observations))

    def to_dict(self) -> dict[str, object]:
        providers = {
            name: {
                "observations": item.observations,
                "successes": item.successes,
                "success_rate": item.success_rate,
                "mean_latency_seconds": item.mean_latency_seconds,
                "p95_latency_seconds": item.p95_latency_seconds,
                "empty_response_count": item.empty_response_count,
                "missing_field_count": item.missing_field_count,
                "error_categories": dict(item.error_categories),
            }
            for name, item in self.providers.items()
        }
        observations = [
            {
                "provider": item.provider,
                "security": item.security,
                "success": item.success,
                "elapsed_seconds": item.elapsed_seconds,
                "rows": item.rows,
                "missing_fields": list(item.missing_fields),
                "error_type": item.error_type,
                "error_message": item.error_message,
                "factor_coverage_complete": item.factor_coverage_complete,
                "factor_values_valid": item.factor_values_valid,
            }
            for item in self.observations
        ]
        return {
            "gateVersion": self.gate_version,
            "providers": providers,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "requiredChecks": dict(self.required_checks),
            "diagnosticChecks": dict(self.diagnostic_checks),
            "observations": observations,
        }


def classify_error(exc: BaseException) -> str:
    current: BaseException | None = exc
    seen: set[int] = set()
    fallback = "unknown"
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return "timeout"
        if isinstance(current, ConnectionError):
            return "network"
        if isinstance(current, (ValueError, TypeError, KeyError)):
            fallback = "data"
        else:
            name = type(current).__name__.lower()
            if "timeout" in name:
                return "timeout"
            if "connection" in name:
                return "network"
            if fallback == "unknown":
                fallback = name.removesuffix("error") or "unknown"
        current = current.__cause__ or current.__context__
    return fallback


def percentile(values: Sequence[float], percent: float) -> float:
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _summarize(items: Sequence[ProbeObservation]) -> ProviderReport:
    latencies = [item.elapsed_seconds for item in items]
    errors = Counter(item.error_type for item in items if item.error_type)
    successes = sum(item.success for item in items)
    return ProviderReport(
        observations=len(items),
        successes=successes,
        success_rate=successes / len(items) if items else 0.0,
        mean_latency_seconds=sum(latencies) / len(latencies) if latencies else 0.0,
        p95_latency_seconds=percentile(latencies, 95),
        empty_response_count=sum(item.success and item.rows <= 0 for item in items),
        missing_field_count=sum(len(item.missing_fields) for item in items),
        error_categories=dict(sorted(errors.items())),
    )


def evaluate_gate(observations: Iterable[ProbeObservation]) -> ProbeReport:
    items = tuple(observations)
    grouped = {provider: [] for provider in CANONICAL_PROVIDERS}
    for item in items:
        grouped.setdefault(item.provider, []).append(item)
    providers = {name: _summarize(group) for name, group in grouped.items()}

    def clean(provider: str, expected: int, *, minimum_rate: float = 1.0) -> bool:
        group = grouped[provider]
        return (
            len(group) == expected
            and providers[provider].success_rate >= minimum_rate
            and not providers[provider].empty_response_count
            and not providers[provider].missing_field_count
        )

    factors = grouped[FACTOR_PROVIDER]
    factor_ok = clean(FACTOR_PROVIDER, 6) and all(
        item.factor_coverage_complete is True and item.factor_values_valid is True
        for item in factors
    )
    required = {
        "tencentStocks": clean(TENCENT_PROVIDER, 10, minimum_rate=0.8),
        "tencentIndexes": clean(INDEX_PROVIDER, 2),
        "sinaFactors": factor_ok,
        "sinaRawFallback": clean(SINA_PROVIDER, 2),
        "tradingCalendar": clean(CALENDAR_PROVIDER, 1),
    }
    reasons = [
        message
        for key, message in (
            ("tencentStocks", "Tencent stock checks did not meet the 80% threshold."),
            ("tencentIndexes", "Tencent index checks require both SH and SZ indexes."),
            ("sinaFactors", "Sina factor coverage or values are incomplete."),
            ("sinaRawFallback", "Sina raw fallback checks require SH and SZ success."),
            ("tradingCalendar", "The Sina trading calendar check failed."),
        )
        if not required[key]
    ]
    eastmoney_ok = bool(grouped[EASTMONEY_PROVIDER]) and all(
        item.success for item in grouped[EASTMONEY_PROVIDER]
    )
    diagnostic = {"eastmoney": eastmoney_ok}
    warnings = () if eastmoney_ok else ("EastMoney diagnostics failed; production routing is unaffected.",)
    return ProbeReport(
        providers=providers,
        passed=not reasons,
        reasons=tuple(reasons),
        observations=items,
        required_checks=required,
        diagnostic_checks=diagnostic,
        warnings=warnings,
    )


class ProviderProbeRunner:
    def __init__(
        self,
        adapters: Mapping[str, ProviderAdapter] | None = None,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.adapters = dict(adapters) if adapters is not None else self._default_adapters()
        self.today = today

    @staticmethod
    def _default_adapters() -> dict[str, ProviderAdapter]:
        from kline.data.akshare_source import AkShareSource
        from kline.data.eastmoney_source import EastMoneyHttpSource
        from kline.data.tencent_source import TencentHttpSource

        sina = AkShareSource()
        tencent = TencentHttpSource()
        eastmoney = EastMoneyHttpSource()
        return {
            TENCENT_PROVIDER: tencent.fetch_history,
            INDEX_PROVIDER: lambda exchange, _code, start, end: tencent.index_history(
                exchange, start, end
            ),
            FACTOR_PROVIDER: lambda exchange, code, _start, _end: (
                sina.sina_adjustment_factors(exchange, code)
            ),
            SINA_PROVIDER: sina.sina_raw_history,
            CALENDAR_PROVIDER: lambda _exchange, _code, _start, _end: sina.trading_calendar(),
            EASTMONEY_PROVIDER: lambda exchange, code, start, end: eastmoney.fetch_history(
                exchange, code, start, end, fqt=0
            ),
        }

    def run(self, *, quick: bool = False) -> ProbeReport:
        end = self.today()
        start = end - timedelta(days=90)
        stocks = REPRESENTATIVE_SECURITIES[:3] if quick else REPRESENTATIVE_SECURITIES
        targets = [
            *((TENCENT_PROVIDER, exchange, code) for exchange, code in stocks),
            *((INDEX_PROVIDER, exchange, code) for exchange, code in INDEX_TARGETS),
            *((FACTOR_PROVIDER, exchange, code) for exchange, code in (
                FACTOR_SECURITIES[:2] if quick else FACTOR_SECURITIES
            )),
            *((SINA_PROVIDER, exchange, code) for exchange, code in (
                SINA_FALLBACK_SECURITIES[:1] if quick else SINA_FALLBACK_SECURITIES
            )),
            (CALENDAR_PROVIDER, "", "trading-calendar"),
            *((EASTMONEY_PROVIDER, exchange, code) for exchange, code in stocks),
        ]
        observations = tuple(
            self._observe(provider, exchange, code, start, end)
            for provider, exchange, code in targets
        )
        report = evaluate_gate(observations)
        if not quick:
            return report
        return ProbeReport(
            providers=report.providers,
            passed=False,
            reasons=report.reasons + ("Quick mode is diagnostic only and is not a production gate.",),
            observations=report.observations,
            required_checks=report.required_checks,
            diagnostic_checks=report.diagnostic_checks,
            warnings=report.warnings,
        )

    def _observe(
        self, provider: str, exchange: str, code: str, start: date, end: date
    ) -> ProbeObservation:
        began = perf_counter()
        try:
            result = self.adapters[provider](exchange, code, start, end)
            columns = set(getattr(result, "columns", ()))
            missing = (
                tuple(sorted(OHLCV_FIELDS - columns))
                if provider in MARKET_DATA_PROVIDERS else ()
            )
            coverage = values_valid = None
            if provider == FACTOR_PROVIDER:
                required = {"qfq_factor", "hfq_factor"}
                coverage = required.issubset(columns) and not result.empty  # type: ignore[union-attr]
                values_valid = coverage and not result[list(required)].isna().any().any()  # type: ignore[index]
            return ProbeObservation(
                provider=provider,
                security=f"{exchange}{code}" if exchange else code,
                success=True,
                elapsed_seconds=perf_counter() - began,
                rows=len(result),  # type: ignore[arg-type]
                missing_fields=missing,
                factor_coverage_complete=coverage,
                factor_values_valid=values_valid,
            )
        except Exception as exc:
            return ProbeObservation(
                provider=provider,
                security=f"{exchange}{code}" if exchange else code,
                success=False,
                elapsed_seconds=perf_counter() - began,
                rows=0,
                error_type=classify_error(exc),
                error_message=str(exc),
            )

    @staticmethod
    def index_adapter(client: object) -> ProviderAdapter:
        """Compatibility helper for an explicit single-provider index adapter."""
        def fetch(_exchange: str, code: str, start: date, end: date) -> pd.DataFrame:
            frame = client.index_zh_a_hist(  # type: ignore[attr-defined]
                symbol=code, period="daily",
                start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
            )
            return frame
        return fetch
