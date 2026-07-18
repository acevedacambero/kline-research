from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd

from kline.features import compute_daily_features
from kline.features.batch import BatchFeatureBuilder, FeatureDatasetStore


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


def test_feature_store_path_and_manifest_include_all_dependency_versions(tmp_path):
    store = FeatureDatasetStore(tmp_path)
    frame = compute_daily_features(derived_frame(), exchange="sh", code="600000")

    first = store.write(
        "sh", "600000", frame,
        snapshot_version="snapshot-one",
        factor_version="factor-v1",
        limit_rule_version="rules-v1",
        feature_definition_version="features-v1",
    )
    second = store.write(
        "sh", "600000", frame,
        snapshot_version="snapshot-one",
        factor_version="factor-v2",
        limit_rule_version="rules-v1",
        feature_definition_version="features-v1",
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
    }
    assert manifest["rows"] == 260
    assert "ma60" in manifest["missingRates"]


def test_feature_store_reuses_identical_current_output(tmp_path):
    store = FeatureDatasetStore(tmp_path)
    kwargs = {
        "snapshot_version": "snapshot-one",
        "factor_version": "factor-v1",
        "limit_rule_version": "rules-v1",
        "feature_definition_version": "features-v1",
    }

    store.write("sh", "600000", derived_frame(), **kwargs)
    reused = store.write("sh", "600000", derived_frame(), **kwargs)

    assert reused.status == "reused"
    assert reused.rows == 260


def test_batch_builder_skips_feature_computation_for_existing_output(tmp_path, monkeypatch):
    source = tmp_path / "source.parquet"
    derived_frame().to_parquet(source, index=False)
    store = FeatureDatasetStore(tmp_path / "output")
    store.write(
        "sh",
        "600000",
        derived_frame(),
        snapshot_version="snapshot-one",
        factor_version="factor-v1",
        limit_rule_version="cn-equity-v1",
        feature_definition_version="daily-features-v1",
    )
    monkeypatch.setattr(
        "kline.features.batch.compute_daily_features",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("existing P2 output must be reused before computation")
        ),
    )

    report = BatchFeatureBuilder(store).build_security(
        {
            "exchange": "sh",
            "code": "600000",
            "derived_path": str(source),
            "snapshot_version": "snapshot-one",
        }
    )

    assert report.status == "reused"
    assert report.rows == 260


def test_batch_builder_isolates_invalid_security(tmp_path):
    valid_path = tmp_path / "valid.parquet"
    invalid_path = tmp_path / "invalid.parquet"
    derived_frame().to_parquet(valid_path, index=False)
    pd.DataFrame([{"date": date(2024, 1, 1)}]).to_parquet(invalid_path, index=False)
    builder = BatchFeatureBuilder(FeatureDatasetStore(tmp_path / "output"), workers=2)

    report = builder.build_many(
        [
            {"exchange": "sh", "code": "600000", "derived_path": str(valid_path), "snapshot_version": "snapshot-good", "st_status": True},
            {"exchange": "sz", "code": "000001", "derived_path": str(invalid_path), "snapshot_version": "snapshot-bad"},
        ]
    )

    assert report.done == 2
    assert report.rows == 260
    assert len(report.errors) == 1
    assert report.errors[0]["security"] == "sz000001"
    written = pd.read_parquet(report.outputs[0].path)
    assert bool(written.iloc[-1]["is_approx"]) is True
