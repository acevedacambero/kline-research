import pandas as pd
from fastapi.testclient import TestClient

from kline.api import create_app, dataframe_records
from kline.config import Settings


class FakeSource:
    def list_securities(self):
        return [{"exchange": "sh", "code": "600000", "name": "浦发银行"}]

    def stock_history(self, *args, **kwargs):
        return pd.DataFrame()

    def index_history(self, *args, **kwargs):
        return pd.DataFrame()


def test_health_exposes_all_version_keys(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dataSource"] == "AkShare"
    assert body["versions"]["labelDefinitionVersion"] == "daily-v1"
    assert body["versions"]["limitRuleVersion"] == "cn-equity-v1"


def test_validate_akshare_reports_available_securities(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).post("/api/datasets/validate")
    assert response.status_code == 200
    assert response.json()["markets"]["sh"] == 1


def test_dataframe_records_converts_nan_to_json_null():
    frame = pd.DataFrame([{"date": "2024-01-02", "ma60": float("nan"), "close": 10.0}])
    assert dataframe_records(frame) == [{"date": "2024-01-02", "ma60": None, "close": 10.0}]
