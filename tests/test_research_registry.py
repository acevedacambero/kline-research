from kline.research import RESEARCH_RUN_REGISTRY_VERSION, ResearchRunRegistry


def test_research_runs_are_immutable_listable_and_reloadable(tmp_path):
    registry = ResearchRunRegistry(tmp_path)
    saved = registry.save(
        "p4-single-factor",
        {"version": "p4-v1", "sampleCount": 120, "status": "review"},
        parameters={"buckets": 5},
        dependencies={"labelDefinitionVersion": "daily-v2"},
        data_snapshot={"manifestHash": "abc", "securityCount": 10},
        code_version="release-1",
    )

    detail = registry.get(saved["runId"])
    assert detail["registryVersion"] == RESEARCH_RUN_REGISTRY_VERSION
    assert detail["result"]["sampleCount"] == 120
    assert detail["dataSnapshot"]["manifestHash"] == "abc"
    listed = registry.list()
    assert listed["total"] == 1
    assert listed["runs"][0]["summary"]["sampleCount"] == 120
    assert registry.get("../unsafe") is None


def test_same_kind_runs_can_be_compared_but_different_kinds_cannot(tmp_path):
    registry = ResearchRunRegistry(tmp_path)
    first = registry.save(
        "p8-portfolio",
        {"version": "p8", "metrics": {"annualizedReturn": 0.1, "sharpe": 0.8}},
        parameters={"top_fraction": 0.1},
        dependencies={},
        data_snapshot={"manifestHash": "one"},
        code_version="release-1",
    )
    second = registry.save(
        "p8-portfolio",
        {"version": "p8", "metrics": {"annualizedReturn": 0.14, "sharpe": 1.0}},
        parameters={"top_fraction": 0.2},
        dependencies={},
        data_snapshot={"manifestHash": "two"},
        code_version="release-2",
    )
    other = registry.save(
        "p6-scan",
        {"version": "p6", "scannedCount": 10},
        parameters={}, dependencies={}, data_snapshot={}, code_version="release-2",
    )

    comparison = registry.compare(first["runId"], second["runId"])
    annualized = next(item for item in comparison["metrics"] if item["metric"] == "annualizedReturn")
    assert annualized["delta"] == 0.04000000000000001
    assert comparison["parameterChanges"][0]["parameter"] == "top_fraction"
    assert registry.compare(first["runId"], other["runId"]) is None


def test_drift_run_summary_keeps_comparable_risk_metrics(tmp_path):
    registry = ResearchRunRegistry(tmp_path)
    saved = registry.save(
        "drift-monitor",
        {
            "version": "feature-drift-v1",
            "status": "drift",
            "metrics": [
                {
                    "column": "score",
                    "status": "drift",
                    "populationStabilityIndex": 0.31,
                    "standardizedMeanShift": 0.7,
                },
                {
                    "column": "return_20",
                    "status": "stable",
                    "populationStabilityIndex": 0.04,
                    "standardizedMeanShift": 0.1,
                },
            ],
        },
        parameters={"recent_days": 60},
        dependencies={},
        data_snapshot={},
        code_version="release-1",
    )

    summary = registry.get(saved["runId"])["summary"]
    assert summary["maxPopulationStabilityIndex"] == 0.31
    assert summary["maxStandardizedMeanShift"] == 0.7
    assert summary["driftedMetrics"] == 1
