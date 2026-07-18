from __future__ import annotations

import json

from fastapi.testclient import TestClient

from kline.api import create_app
from kline.config import Settings


LABEL_COLUMN = "p20_delayed_executable_return"


def post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    response.raise_for_status()
    result = response.json()
    print(
        json.dumps(
            {
                "event": "research_run",
                "path": path,
                "runId": result.get("runId"),
                "status": result.get("status"),
                "version": result.get("version"),
                "sampleCount": result.get("sampleCount"),
                "auc": result.get("auc"),
                "warnings": result.get("warnings", []),
            },
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )
    return result


def main() -> int:
    settings = Settings(cloudflare_access_required=False)
    with TestClient(create_app(settings)) as client:
        post(
            client,
            "/api/validation/single-factor",
            {"factor_column": "score", "label_column": LABEL_COLUMN, "buckets": 5},
        )
        post(
            client,
            "/api/validation/calibration",
            {"label_column": LABEL_COLUMN, "buckets": 10},
        )
        baseline = post(
            client,
            "/api/model/p7/baseline",
            {"label_column": LABEL_COLUMN, "embargo_days": 7},
        )
        multifeature = post(
            client,
            "/api/model/p7/multifeature",
            {"label_column": LABEL_COLUMN, "embargo_days": 7},
        )
        post(
            client,
            "/api/model/p7/walk-forward",
            {"label_column": LABEL_COLUMN, "folds": 3, "embargo_days": 7},
        )

        candidates = [
            item
            for item in (baseline, multifeature)
            if item.get("status") == "trained"
            and item.get("modelId")
            and item.get("auc") is not None
        ]
        active_model = None
        if candidates:
            selected = max(candidates, key=lambda item: float(item["auc"]))
            response = client.post(
                f"/api/model/p7/registry/{selected['modelId']}/promote"
            )
            response.raise_for_status()
            active_model = response.json()
            print(
                json.dumps(
                    {
                        "event": "model_promoted",
                        "modelId": selected["modelId"],
                        "auc": selected["auc"],
                        "kind": active_model.get("kind"),
                    }
                ),
                flush=True,
            )
        else:
            print(
                json.dumps(
                    {
                        "event": "model_not_promoted",
                        "reason": "no trained model with a measurable out-of-sample AUC",
                    }
                ),
                flush=True,
            )

        post(client, "/api/scan/p3", {"min_score": 70, "limit": 200})
        post(
            client,
            "/api/validation/portfolio",
            {
                "label_column": LABEL_COLUMN,
                "top_fraction": 0.1,
                "non_overlapping": True,
                "transaction_cost_bps": 10,
                "slippage_bps": 10,
            },
        )
        acceptance = client.get("/api/system/research-acceptance")
        acceptance.raise_for_status()
        print(
            json.dumps(
                {"event": "final_acceptance", "report": acceptance.json()},
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
