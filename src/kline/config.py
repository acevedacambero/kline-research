from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_path: Path = Path("data")
    history_start_date: str = "19900101"
    request_retries: int = 3
    security_fetch_timeout_seconds: int = 60
    download_workers: int = 8
    model_config = SettingsConfigDict(env_prefix="KLINE_", env_file=".env", extra="ignore")


VERSIONS = {
    "dataSourceVersion": "akshare-raw-v1",
    "factorDefinitionVersion": "akshare-sina-factor-v1",
    "derivedAdjustmentVersion": "raw-factor-engine-v1",
    "algorithmVersion": "p1-v1",
    "rightsVersion": "akshare-factor-v1",
    "featureDefinitionVersion": "daily-features-v1",
    "scoreDefinitionVersion": "not-applicable",
    "labelDefinitionVersion": "daily-v1",
    "limitRuleVersion": "cn-equity-v1",
    "gapRuleVersion": "calendar-10d-v1",
    "labelMaturityRuleVersion": "trading-days-v1",
    "independentPeriodDefinitionVersion": "two-stage-7d-v1",
    "marketRegimeDefinitionVersion": "not-applicable",
    "transactionCostVersion": "not-applicable",
    "slippageModelVersion": "not-applicable",
}
