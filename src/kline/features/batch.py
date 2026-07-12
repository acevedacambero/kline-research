from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from kline.config import VERSIONS
from kline.storage import atomic_write_parquet, atomic_write_text

from .core import FEATURE_DEFINITION_VERSION, compute_daily_features


@dataclass(frozen=True)
class FeatureStoreReport:
    status: str
    path: str
    manifest_path: str
    rows: int


@dataclass(frozen=True)
class BatchFeatureReport:
    done: int
    rows: int
    errors: list[dict[str, str]]
    outputs: list[FeatureStoreReport]


class FeatureDatasetStore:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)

    def write(
        self,
        exchange: str,
        code: str,
        frame: pd.DataFrame,
        *,
        snapshot_version: str,
        factor_version: str,
        limit_rule_version: str,
        feature_definition_version: str,
    ) -> FeatureStoreReport:
        identity = "__".join(
            (snapshot_version, factor_version, limit_rule_version)
        ).replace("/", "-").replace("\\", "-")
        root = (
            self.output_root
            / "data-foundation-v1"
            / "features"
            / feature_definition_version
            / identity
            / exchange
        )
        path = root / f"{code}.parquet"
        manifest_path = root / f"{code}.manifest.json"
        if path.exists() and manifest_path.exists():
            return FeatureStoreReport("reused", str(path), str(manifest_path), len(frame))

        root.mkdir(parents=True, exist_ok=True)
        atomic_write_parquet(frame, path)
        missing_rates = {
            column: round(float(frame[column].isna().mean()), 8)
            for column in frame.columns
        }
        manifest = {
            "security": f"{exchange}{code}",
            "rows": len(frame),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "versions": {
                "snapshotVersion": snapshot_version,
                "factorVersion": factor_version,
                "limitRuleVersion": limit_rule_version,
                "featureDefinitionVersion": feature_definition_version,
            },
            "missingRates": missing_rates,
            "approximateRuleRatio": (
                round(float(frame["is_approx"].fillna(False).mean()), 8)
                if "is_approx" in frame else None
            ),
        }
        atomic_write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), manifest_path
        )
        return FeatureStoreReport("written", str(path), str(manifest_path), len(frame))


class BatchFeatureBuilder:
    def __init__(self, store: FeatureDatasetStore):
        self.store = store

    def build_security(self, security: dict[str, Any]) -> FeatureStoreReport:
        frame = pd.read_parquet(security["derived_path"])
        factor_version = (
            str(frame["factor_version"].dropna().iloc[0])
            if "factor_version" in frame and not frame["factor_version"].dropna().empty
            else "unknown"
        )
        features = compute_daily_features(
            frame,
            exchange=security["exchange"],
            code=security["code"],
            st_status=bool(security.get("st_status", False)),
        )
        return self.store.write(
            security["exchange"],
            security["code"],
            features,
            snapshot_version=security["snapshot_version"],
            factor_version=factor_version,
            limit_rule_version=VERSIONS["limitRuleVersion"],
            feature_definition_version=FEATURE_DEFINITION_VERSION,
        )

    def build_many(
        self,
        securities: Iterable[dict[str, Any]],
        on_progress: Callable[[str, FeatureStoreReport | None, Exception | None], None]
        | None = None,
    ) -> BatchFeatureReport:
        rows = 0
        done = 0
        errors: list[dict[str, str]] = []
        outputs: list[FeatureStoreReport] = []
        for security in securities:
            security_key = f'{security["exchange"]}{security["code"]}'
            try:
                report = self.build_security(security)
                outputs.append(report)
                rows += report.rows
                if on_progress:
                    on_progress(security_key, report, None)
            except Exception as exc:
                errors.append({"security": security_key, "message": str(exc)})
                if on_progress:
                    on_progress(security_key, None, exc)
            finally:
                done += 1
        return BatchFeatureReport(done, rows, errors, outputs)
