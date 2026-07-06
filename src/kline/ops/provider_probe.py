"""Provider probe observations and deployment-gate evaluation.

Canonical provider names are lower-case: ``eastmoney``, ``tencent``, ``sina``,
``index``, and ``calendar``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from time import perf_counter
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd


EASTMONEY_PROVIDER = "eastmoney"
TENCENT_PROVIDER = "tencent"
SINA_PROVIDER = "sina"
INDEX_PROVIDER = "index"
CALENDAR_PROVIDER = "calendar"

CANONICAL_PROVIDERS = (
    EASTMONEY_PROVIDER,
    TENCENT_PROVIDER,
    SINA_PROVIDER,
    INDEX_PROVIDER,
    CALENDAR_PROVIDER,
)
MARKET_DATA_PROVIDERS = frozenset(
    {EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER, INDEX_PROVIDER}
)
OHLCV_FIELDS = frozenset({"open", "high", "low", "close", "volume"})

REPRESENTATIVE_SECURITIES = (
    ("sh", "600000"),
    ("sz", "000001"),
    ("bj", "430047"),
    ("sh", "688981"),
    ("sz", "300750"),
    ("sh", "600519"),
    ("sz", "002594"),
    ("sh", "601318"),
    ("sz", "000858"),
    ("sh", "688036"),
)

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
    observations: tuple[ProbeObservation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "observations", tuple(self.observations))

    def to_dict(self) -> dict[str, object]:
        """Return a detached structure containing only JSON-compatible containers."""
        providers = {
            name: {
                "observations": summary.observations,
                "successes": summary.successes,
                "success_rate": summary.success_rate,
                "mean_latency_seconds": summary.mean_latency_seconds,
                "p95_latency_seconds": summary.p95_latency_seconds,
                "empty_response_count": summary.empty_response_count,
                "missing_field_count": summary.missing_field_count,
                "error_categories": dict(summary.error_categories),
            }
            for name, summary in self.providers.items()
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
            }
            for item in self.observations
        ]
        return {
            "providers": providers,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "observations": observations,
        }


def classify_error(exc: BaseException) -> str:
    """Return a stable, low-cardinality category for a probe exception."""
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
    """Calculate a percentile with linear interpolation between nearest ranks."""
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
    successes = sum(item.success for item in items)
    latencies = [item.elapsed_seconds for item in items]
    errors = Counter(item.error_type for item in items if item.error_type)
    return ProviderReport(
        observations=len(items),
        successes=successes,
        success_rate=successes / len(items) if items else 0.0,
        mean_latency_seconds=sum(latencies) / len(latencies) if latencies else 0.0,
        p95_latency_seconds=percentile(latencies, 95),
        empty_response_count=sum(item.success and item.rows <= 0 for item in items),
        missing_field_count=sum(len(item.missing_fields) for item in items),
        error_categories=MappingProxyType(dict(sorted(errors.items()))),
    )


def evaluate_gate(observations: Iterable[ProbeObservation]) -> ProbeReport:
    """Aggregate observations and evaluate all provider-readiness thresholds."""
    items = tuple(observations)
    grouped = {provider: [] for provider in CANONICAL_PROVIDERS}
    for item in items:
        grouped.setdefault(item.provider, []).append(item)

    providers = {name: _summarize(group) for name, group in grouped.items()}
    reasons: list[str] = []

    if not items:
        reasons.append("No probe observations were provided.")

    eastmoney_rate = providers[EASTMONEY_PROVIDER].success_rate
    if not grouped[EASTMONEY_PROVIDER]:
        reasons.append("No EastMoney observations were provided.")
    if eastmoney_rate < 0.9:
        reasons.append(f"EastMoney success rate {eastmoney_rate:.1%} is below 90%.")

    tencent_rate = providers[TENCENT_PROVIDER].success_rate
    if not grouped[TENCENT_PROVIDER]:
        reasons.append("No Tencent observations were provided.")
    if tencent_rate < 0.8:
        reasons.append(f"Tencent success rate {tencent_rate:.1%} is below 80%.")

    if not any(item.success and item.provider == SINA_PROVIDER for item in items):
        reasons.append("Sina has no successful observation.")
    if not any(item.success and item.provider == INDEX_PROVIDER for item in items):
        reasons.append("The index probe did not succeed.")
    if not any(item.success and item.provider == CALENDAR_PROVIDER for item in items):
        reasons.append("The calendar probe did not succeed.")

    empty_successes = [item for item in items if item.success and item.rows <= 0]
    if empty_successes:
        reasons.append(f"{len(empty_successes)} successful probe(s) returned an empty response.")

    incomplete = [
        item
        for item in items
        if item.success
        and item.provider in MARKET_DATA_PROVIDERS
        and OHLCV_FIELDS.intersection(item.missing_fields)
    ]
    if incomplete:
        reasons.append(
            f"{len(incomplete)} successful stock/index probe(s) have missing required OHLCV fields."
        )

    return ProbeReport(
        providers=MappingProxyType(providers),
        passed=not reasons,
        reasons=tuple(reasons),
        observations=items,
    )


class ProviderProbeRunner:
    """Execute an isolated, non-aborting readiness probe across data providers."""

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
        from kline.data.eastmoney_source import EastMoneyHttpSource
        from kline.data.tencent_source import TencentHttpSource

        eastmoney = EastMoneyHttpSource()
        tencent = TencentHttpSource()

        def sina(exchange: str, code: str, start: date, end: date):
            return ak.stock_zh_a_daily(
                symbol=f"{exchange}{code}",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
            )

        import akshare as ak

        def calendar(_exchange: str, _code: str, _start: date, _end: date):
            from kline.data.akshare_source import AkShareSource

            return AkShareSource(client=ak).trading_calendar()

        return {
            EASTMONEY_PROVIDER: lambda exchange, code, start, end: eastmoney.fetch_history(
                exchange, code, start, end, fqt=0
            ),
            TENCENT_PROVIDER: tencent.fetch_history,
            SINA_PROVIDER: sina,
            INDEX_PROVIDER: ProviderProbeRunner.index_adapter(ak),
            CALENDAR_PROVIDER: calendar,
        }

    @staticmethod
    def index_adapter(client: object) -> ProviderAdapter:
        """Build an index probe that never invokes an alternate provider."""

        def fetch(_exchange: str, code: str, start: date, end: date) -> pd.DataFrame:
            frame = client.index_zh_a_hist(  # type: ignore[attr-defined]
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            aliases = {
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
            }
            normalized = frame.rename(columns=aliases)
            required = ["date", "open", "high", "low", "close", "volume"]
            missing = [column for column in required if column not in normalized.columns]
            if missing:
                raise ValueError(f"index_zh_a_hist missing columns: {', '.join(missing)}")
            columns = required + (["amount"] if "amount" in normalized.columns else [])
            result = normalized[columns].copy()
            result["date"] = pd.to_datetime(result["date"], errors="raise").dt.date
            for column in columns[1:]:
                result[column] = pd.to_numeric(result[column], errors="raise")
            return result.sort_values("date").drop_duplicates("date").reset_index(drop=True)

        return fetch

    def run(self, *, quick: bool = False) -> ProbeReport:
        end = self.today()
        start = end - timedelta(days=90)
        stocks = REPRESENTATIVE_SECURITIES[:3] if quick else REPRESENTATIVE_SECURITIES
        targets = [
            *((EASTMONEY_PROVIDER, exchange, code) for exchange, code in stocks),
            *((TENCENT_PROVIDER, exchange, code) for exchange, code in stocks),
            *((SINA_PROVIDER, exchange, code) for exchange, code in stocks[: (1 if quick else 3)]),
            (INDEX_PROVIDER, "sh", "000001"),
            (CALENDAR_PROVIDER, "", "trading-calendar"),
        ]
        observations = [
            self._observe(provider, exchange, code, start, end)
            for provider, exchange, code in targets
        ]
        report = evaluate_gate(observations)
        if quick:
            return ProbeReport(
                providers=report.providers,
                passed=False,
                reasons=report.reasons
                + ("Quick mode is diagnostic only and is not a production gate.",),
                observations=report.observations,
            )
        return report

    def _observe(
        self, provider: str, exchange: str, code: str, start: date, end: date
    ) -> ProbeObservation:
        began = perf_counter()
        try:
            result = self.adapters[provider](exchange, code, start, end)
            columns = set(getattr(result, "columns", ()))
            missing = (
                tuple(sorted(OHLCV_FIELDS - columns))
                if provider in MARKET_DATA_PROVIDERS
                else ()
            )
            return ProbeObservation(
                provider=provider,
                security=f"{exchange}{code}" if exchange else code,
                success=True,
                elapsed_seconds=perf_counter() - began,
                rows=len(result),  # type: ignore[arg-type]
                missing_fields=missing,
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
