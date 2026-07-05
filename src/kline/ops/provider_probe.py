"""Provider probe observations and deployment-gate evaluation.

Canonical provider names are lower-case: ``eastmoney``, ``tencent``, ``sina``,
``index``, and ``calendar``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence


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
OHLCV_FIELDS = frozenset({"open", "high", "low", "close", "volume"})


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


@dataclass(frozen=True)
class ProbeReport:
    providers: Mapping[str, ProviderReport]
    passed: bool
    reasons: tuple[str, ...]


def classify_error(exc: BaseException) -> str:
    """Return a stable, low-cardinality category for a probe exception."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "network"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "data"

    name = type(exc).__name__.lower()
    return name.removesuffix("error") or "unknown"


def percentile(values: Sequence[float], percent: float) -> float:
    """Calculate a percentile with linear interpolation between nearest ranks."""
    if not values:
        return 0.0
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")

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
        empty_response_count=sum(item.rows <= 0 for item in items),
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
    if eastmoney_rate < 0.9:
        reasons.append(f"EastMoney success rate {eastmoney_rate:.1%} is below 90%.")

    tencent_rate = providers[TENCENT_PROVIDER].success_rate
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
        and item.security in {"stock", "index"}
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
    )
