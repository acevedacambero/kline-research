from __future__ import annotations

import json

from fastapi.testclient import TestClient

from kline.api import create_app
from kline.config import Settings


def main() -> int:
    settings = Settings(cloudflare_access_required=False)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/system/research-acceptance")
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
