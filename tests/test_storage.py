from pathlib import Path

import pandas as pd
import pytest

from kline.storage import atomic_write_parquet, atomic_write_text


def test_atomic_parquet_failure_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "dataset.parquet"
    target.write_bytes(b"previous-complete-file")

    def fail_after_partial_write(_frame, path, **_kwargs):
        Path(path).write_bytes(b"partial")
        raise RuntimeError("disk interrupted")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="disk interrupted"):
        atomic_write_parquet(pd.DataFrame([{"value": 1}]), target)

    assert target.read_bytes() == b"previous-complete-file"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_parquet_and_text_replace_only_after_success(tmp_path):
    parquet = tmp_path / "nested" / "dataset.parquet"
    manifest = tmp_path / "nested" / "dataset.json"

    atomic_write_parquet(pd.DataFrame([{"value": 7}]), parquet)
    atomic_write_text('{"status":"ok"}', manifest)

    assert pd.read_parquet(parquet).to_dict("records") == [{"value": 7}]
    assert manifest.read_text(encoding="utf-8") == '{"status":"ok"}'
