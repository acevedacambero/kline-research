from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_path: Path = Path("data")
    jobs_db_path: Path | None = None
    duckdb_memory_limit: str = "2GB"
    duckdb_threads: int = 2
    market_timezone: str = "Asia/Shanghai"
    history_start_date: str = "19900101"
    request_retries: int = 3
    security_fetch_timeout_seconds: int = 60
    download_workers: int = 8
    history_backfill_min_days: int = Field(default=250, ge=1)
    history_backfill_freshness_days: int = Field(default=10, ge=1)
    research_freshness_min_coverage: float = Field(default=0.95, ge=0, le=1)
    provider_gate_max_age_hours: int = Field(default=24, ge=1)
    maintenance_auto_enabled: bool = False
    maintenance_hour: int = Field(default=18, ge=0, le=23)
    maintenance_minute: int = Field(default=30, ge=0, le=59)
    backup_path: Path | None = None
    frontend_dist_path: Path | None = None
    cloudflare_access_required: bool = False
    cloudflare_access_team_domain: str = ""
    cloudflare_access_audience: str = ""
    cloudflare_access_allowed_emails: str = ""
    model_config = SettingsConfigDict(env_prefix="KLINE_", env_file=".env", extra="ignore")


VERSIONS = {
    "providerPolicyVersion": "sh-sz-tencent-sina-v1",
    "dataSourceVersion": "akshare-raw-v1",
    "factorDefinitionVersion": "akshare-sina-factor-v1",
    "derivedAdjustmentVersion": "raw-factor-engine-v1",
    "algorithmVersion": "p1-v1",
    "rightsVersion": "akshare-factor-v1",
    "featureDefinitionVersion": "daily-features-v1",
    "scoreDefinitionVersion": "p3-rule-score-v1",
    "singleFactorValidationVersion": "p4-single-factor-v4-stability",
    "calibrationDefinitionVersion": "p5-score-calibration-v3-quality",
    "modelDefinitionVersion": "p7-score-logistic-v1",
    "multiFeatureModelDefinitionVersion": "p7-multifeature-logistic-v1",
    "modelRegistryVersion": "p7-model-registry-v1",
    "walkForwardModelDefinitionVersion": "p7-walk-forward-v2-nonoverlap",
    "portfolioValidationVersion": "p8-top-score-portfolio-v4-benchmark",
    "labelDefinitionVersion": "daily-v2-exit-delay",
    "limitRuleVersion": "cn-equity-v1",
    "gapRuleVersion": "calendar-10d-v1",
    "labelMaturityRuleVersion": "trading-days-v1",
    "independentPeriodDefinitionVersion": "two-stage-7d-v1",
    "marketRegimeDefinitionVersion": "not-applicable",
    "transactionCostVersion": "p8-flat-bps-v1",
    "slippageModelVersion": "p8-flat-slippage-bps-v1",
    "researchReadinessVersion": "research-gate-v3-provider-expiry",
    "researchRunRegistryVersion": "research-run-registry-v1",
    "isolationRuleVersion": "purged-embargo-v1",
}
