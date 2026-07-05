import json
from pathlib import Path

from kline.api import create_app


target = Path(__file__).parents[1] / "web" / "openapi.json"
target.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print(target)
