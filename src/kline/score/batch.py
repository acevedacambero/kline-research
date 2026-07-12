from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from kline.storage import atomic_write_parquet, atomic_write_text

from kline.config import VERSIONS
from kline.features import FEATURE_DEFINITION_VERSION, compute_daily_features
from kline.features.batch import FeatureDatasetStore

from .core import SCORE_DEFINITION_VERSION, compute_rule_score


@dataclass(frozen=True)
class ScoreStoreReport:
    status: str
    path: str
    manifest_path: str
    rows: int


@dataclass(frozen=True)
class BatchScoreReport:
    done: int
    rows: int
    errors: list[dict[str, str]]
    outputs: list[ScoreStoreReport]


def compute_score_frame(
    bars: pd.DataFrame | list[dict],
    *,
    exchange: str,
    code: str,
    st_status: bool = False,
) -> pd.DataFrame:
    features = compute_daily_features(bars, exchange=exchange, code=code, st_status=st_status)
    return compute_score_frame_from_features(features)


def compute_score_frame_from_features(features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in features.to_dict("records"):
        score = compute_rule_score(row)
        components = score["components"]
        rows.append(
            {
                "date": row["date"],
                "exchange": row["exchange"],
                "code": row["code"],
                "available_history": row["available_history"],
                "score": score["score"],
                "grade": score["grade"],
                "usable": score["usable"],
                "trend_score": components["trend"]["score"],
                "position_score": components["position"]["score"],
                "momentum_score": components["momentum"]["score"],
                "volume_price_score": components["volumePrice"]["score"],
                "trading_behavior_score": components["tradingBehavior"]["score"],
                "reasons": score["reasons"],
                "component_reasons": {key: value["reasons"] for key, value in components.items()},
                "price_basis": row["price_basis"],
                "feature_definition_version": FEATURE_DEFINITION_VERSION,
                "score_definition_version": SCORE_DEFINITION_VERSION,
                "limit_rule_version": VERSIONS["limitRuleVersion"],
                "factor_version": row.get("factor_version"),
            }
        )
    return pd.DataFrame(rows)


class ScoreDatasetStore:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)

    def paths_for(
        self,
        exchange: str,
        code: str,
        *,
        snapshot_version: str,
        factor_version: str,
        limit_rule_version: str,
        feature_definition_version: str,
        score_definition_version: str,
    ) -> tuple[Path, Path]:
        identity = (
            "__".join(
                (snapshot_version, factor_version, limit_rule_version, feature_definition_version)
            )
            .replace("/", "-")
            .replace("\\", "-")
        )
        root = (
            self.output_root
            / "data-foundation-v1"
            / "scores"
            / score_definition_version
            / identity
            / exchange
        )
        return root / f"{code}.parquet", root / f"{code}.manifest.json"

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
        score_definition_version: str,
    ) -> ScoreStoreReport:
        path, manifest_path = self.paths_for(
            exchange,
            code,
            snapshot_version=snapshot_version,
            factor_version=factor_version,
            limit_rule_version=limit_rule_version,
            feature_definition_version=feature_definition_version,
            score_definition_version=score_definition_version,
        )
        if path.exists() and manifest_path.exists():
            return ScoreStoreReport("reused", str(path), str(manifest_path), len(frame))

        root = path.parent
        root.mkdir(parents=True, exist_ok=True)
        atomic_write_parquet(frame, path)
        manifest = {
            "security": f"{exchange}{code}",
            "rows": len(frame),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "versions": {
                "snapshotVersion": snapshot_version,
                "factorVersion": factor_version,
                "limitRuleVersion": limit_rule_version,
                "featureDefinitionVersion": feature_definition_version,
                "scoreDefinitionVersion": score_definition_version,
            },
            "usableRatio": (
                round(float(frame["usable"].fillna(False).mean()), 8) if "usable" in frame else None
            ),
            "averageScore": (
                round(float(frame["score"].dropna().mean()), 8)
                if "score" in frame and not frame["score"].dropna().empty
                else None
            ),
        }
        atomic_write_text(json.dumps(manifest, ensure_ascii=False, indent=2), manifest_path)
        return ScoreStoreReport("written", str(path), str(manifest_path), len(frame))


class BatchScoreBuilder:
    def __init__(self, store: ScoreDatasetStore):
        self.store = store

    def build_security(self, security: dict[str, Any]) -> ScoreStoreReport:
        frame = pd.read_parquet(security["derived_path"])
        factor_version = (
            str(frame["factor_version"].dropna().iloc[0])
            if "factor_version" in frame and not frame["factor_version"].dropna().empty
            else "unknown"
        )
        score_path, score_manifest_path = self.store.paths_for(
            security["exchange"],
            security["code"],
            snapshot_version=security["snapshot_version"],
            factor_version=factor_version,
            limit_rule_version=VERSIONS["limitRuleVersion"],
            feature_definition_version=FEATURE_DEFINITION_VERSION,
            score_definition_version=SCORE_DEFINITION_VERSION,
        )
        if score_path.exists() and score_manifest_path.exists():
            manifest = json.loads(score_manifest_path.read_text(encoding="utf-8"))
            return ScoreStoreReport(
                "reused", str(score_path), str(score_manifest_path), int(manifest.get("rows", 0))
            )
        feature_path = FeatureDatasetStore(self.store.output_root).path_for(
            security["exchange"],
            security["code"],
            snapshot_version=security["snapshot_version"],
            factor_version=factor_version,
            limit_rule_version=VERSIONS["limitRuleVersion"],
            feature_definition_version=FEATURE_DEFINITION_VERSION,
        )
        features = (
            pd.read_parquet(feature_path)
            if feature_path.exists()
            else compute_daily_features(
                frame,
                exchange=security["exchange"],
                code=security["code"],
                st_status=bool(security.get("st_status", False)),
            )
        )
        scores = compute_score_frame_from_features(features)
        return self.store.write(
            security["exchange"],
            security["code"],
            scores,
            snapshot_version=security["snapshot_version"],
            factor_version=factor_version,
            limit_rule_version=VERSIONS["limitRuleVersion"],
            feature_definition_version=FEATURE_DEFINITION_VERSION,
            score_definition_version=SCORE_DEFINITION_VERSION,
        )

    def build_many(
        self,
        securities: Iterable[dict[str, Any]],
        on_progress: Callable[[str, ScoreStoreReport | None, Exception | None], None] | None = None,
    ) -> BatchScoreReport:
        rows = 0
        done = 0
        errors: list[dict[str, str]] = []
        outputs: list[ScoreStoreReport] = []
        for security in securities:
            security_key = f"{security['exchange']}{security['code']}"
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
        return BatchScoreReport(done, rows, errors, outputs)
