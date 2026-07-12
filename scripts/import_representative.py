from datetime import date

from kline.config import Settings
from kline.data.akshare_source import AkShareSource
from kline.data.pipeline import DatasetPipeline
from kline.data.provider_policy import REPRESENTATIVE_SECURITIES


settings = Settings()
source = AkShareSource()
pipeline = DatasetPipeline(settings.data_path)
pipeline.initialize_catalog()
start = date.fromisoformat(
    f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-{settings.history_start_date[6:]}"
)
for exchange, code, _name in REPRESENTATIVE_SECURITIES:
    raw = source.stock_history(code, start, date.today(), "")
    factors = source.adjustment_factors(code)
    result = pipeline.import_security(exchange, code, raw, factors)
    print(result.status, f"{exchange}{code}", result.normalized_path)
