from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd

from kline.score.batch import BatchScoreBuilder, ScoreDatasetStore, compute_score_frame
from kline.features import compute_daily_features
from kline.features.batch import FeatureDatasetStore


def derived_frame(count: int = 260) -> pd.DataFrame:
    rows = []
    for index in range(count):
        close = 10.0 + index / 10
        rows.append(
            {
                "date": date(2023, 1, 1) + timedelta(days=index),
                "open": close,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "open_qfq": close,
                "high_qfq": close + 0.2,
                "low_qfq": close - 0.2,
                "close_qfq": close,
                "close_total_return": close,
                "volume": 1000 + index,
                "amount": 10000 + index,
                "factor_version": "factor-v1",
            }
        )
    return pd.DataFrame(rows)


def test_score_frame_preserves_point_in_time_rows_and_explanations():
    frame = compute_score_frame(derived_frame(), exchange="sh", code="600000")

    assert len(frame) == 260
    assert frame.iloc[-1]["score_definition_version"] == "p3-rule-score-v1"
    assert 0 <= frame.iloc[-1]["score"] <= 100
    assert frame.iloc[-1]["grade"] in {"A", "B", "C", "D"}
    assert "trend_score" in frame.columns
    assert isinstance(frame.iloc[-1]["reasons"], list)


def test_score_store_path_and_manifest_include_dependency_versions(tmp_path):
    store = ScoreDatasetStore(tmp_path)
    frame = compute_score_frame(derived_frame(), exchange="sh", code="600000")

    first = store.write(
        "sh",
        "600000",
        frame,
        snapshot_version="snapshot-one",
        factor_version="factor-v1",
        limit_rule_version="rules-v1",
        feature_definition_version="features-v1",
        score_definition_version="scores-v1",
    )
    second = store.write(
        "sh",
        "600000",
        frame,
        snapshot_version="snapshot-one",
        factor_version="factor-v1",
        limit_rule_version="rules-v1",
        feature_definition_version="features-v1",
        score_definition_version="scores-v2",
    )

    assert first.status == "written"
    assert Path(first.path).exists()
    assert first.path != second.path
    manifest = json.loads(Path(first.manifest_path).read_text(encoding="utf-8"))
    assert manifest["versions"] == {
        "snapshotVersion": "snapshot-one",
        "factorVersion": "factor-v1",
        "limitRuleVersion": "rules-v1",
        "featureDefinitionVersion": "features-v1",
        "scoreDefinitionVersion": "scores-v1",
    }
    assert manifest["rows"] == 260
    assert 0 <= manifest["usableRatio"] <= 1


def test_batch_score_builder_isolates_invalid_security(tmp_path):
    valid_path = tmp_path / "valid.parquet"
    invalid_path = tmp_path / "invalid.parquet"
    derived_frame().to_parquet(valid_path, index=False)
    pd.DataFrame([{"date": date(2024, 1, 1)}]).to_parquet(invalid_path, index=False)
    builder = BatchScoreBuilder(ScoreDatasetStore(tmp_path / "output"))

    report = builder.build_many(
        [
            {
                "exchange": "sh",
                "code": "600000",
                "derived_path": str(valid_path),
                "snapshot_version": "snapshot-good",
                "st_status": False,
            },
            {
                "exchange": "sz",
                "code": "000001",
                "derived_path": str(invalid_path),
                "snapshot_version": "snapshot-bad",
            },
        ]
    )

    assert report.done == 2
    assert report.rows == 260
    assert len(report.errors) == 1
    assert report.errors[0]["security"] == "sz000001"
    written = pd.read_parquet(report.outputs[0].path)
    assert written.iloc[-1]["code"] == "600000"


def test_score_builder_reuses_matching_offline_features(tmp_path, monkeypatch):
    derived_path = tmp_path / "derived.parquet"
    bars = derived_frame()
    bars.to_parquet(derived_path, index=False)
    output = tmp_path / "output"
    features = compute_daily_features(bars, exchange="sh", code="600000")
    FeatureDatasetStore(output).write(
        "sh",
        "600000",
        features,
        snapshot_version="snapshot-one",
        factor_version="factor-v1",
        limit_rule_version="cn-equity-v1",
        feature_definition_version="daily-features-v1",
    )

    def should_not_recompute(*_args, **_kwargs):
        raise AssertionError("matching P2 features must be reused")

    monkeypatch.setattr("kline.score.batch.compute_daily_features", should_not_recompute)
    report = BatchScoreBuilder(ScoreDatasetStore(output)).build_security(
        {
            "exchange": "sh",
            "code": "600000",
            "derived_path": str(derived_path),
            "snapshot_version": "snapshot-one",
        }
    )

    assert report.status == "written"
    assert report.rows == len(features)
    written = pd.read_parquet(report.path)
    assert written.iloc[-1]["code"] == "600000"


def test_score_builder_skips_score_computation_when_output_exists(tmp_path, monkeypatch):
    derived_path = tmp_path / "derived.parquet"
    bars = derived_frame()
    bars.to_parquet(derived_path, index=False)
    store = ScoreDatasetStore(tmp_path / "output")
    frame = compute_score_frame(bars, exchange="sh", code="600000")
    first = store.write(
        "sh",
        "600000",
        frame,
        snapshot_version="snapshot-one",
        factor_version="factor-v1",
        limit_rule_version="cn-equity-v1",
        feature_definition_version="daily-features-v1",
        score_definition_version="p3-rule-score-v1",
    )

    def should_not_compute(*_args, **_kwargs):
        raise AssertionError("existing P3 output must be reused before score computation")

    monkeypatch.setattr("kline.score.batch.compute_score_frame_from_features", should_not_compute)
    report = BatchScoreBuilder(store).build_security(
        {
            "exchange": "sh",
            "code": "600000",
            "derived_path": str(derived_path),
            "snapshot_version": "snapshot-one",
        }
    )

    assert report.status == "reused"
    assert report.path == first.path
    assert report.rows == len(frame)
