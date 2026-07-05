from datetime import date

from kline.config import Settings
from kline.data.akshare_source import AkShareSource
from kline.data.pipeline import DatasetPipeline


settings = Settings()
source = AkShareSource()
pipeline = DatasetPipeline(settings.data_path)
pipeline.initialize_catalog()
preferred = (("sh", "600000"), ("sz", "000001"), ("bj", "920001"))
start = date.fromisoformat(
    f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-{settings.history_start_date[6:]}"
)
for exchange, code in preferred:
    raw = source.stock_history(code, start, date.today(), "")
    factors = source.adjustment_factors(code)
    result = pipeline.import_security(exchange, code, raw, factors)
    print(result.status, f"{exchange}{code}", result.normalized_path)
