import json
from pathlib import Path

from kline.model.registry import MODEL_REGISTRY_VERSION, ModelRegistry


def test_model_registry_saves_deterministic_versioned_artifact(tmp_path):
    registry = ModelRegistry(tmp_path)
    result = {
        "version": "p7-score-logistic-v1",
        "status": "trained",
        "labelColumn": "p20_executable_return",
        "coefficient": 0.5,
    }
    dependencies = {
        "scoreDefinitionVersion": "p3-rule-score-v1",
        "labelDefinitionVersion": "daily-v2-exit-delay",
    }

    first = registry.save("baseline", result, dependencies=dependencies)
    second = registry.save("baseline", result, dependencies=dependencies)

    assert first["modelId"] == second["modelId"]
    path = Path(first["artifactPath"])
    assert path.exists()
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["registryVersion"] == MODEL_REGISTRY_VERSION
    assert artifact["dependencies"] == dependencies


def test_model_registry_lists_artifacts_and_isolates_invalid_files(tmp_path):
    registry = ModelRegistry(tmp_path)
    saved = registry.save(
        "multifeature",
        {"version": "model-v1", "status": "trained", "labelColumn": "label"},
        dependencies={"featureDefinitionVersion": "features-v1"},
    )
    invalid = registry.root / "baseline" / "broken.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("not-json", encoding="utf-8")

    status = registry.list()

    assert status["version"] == MODEL_REGISTRY_VERSION
    assert status["artifacts"][0]["modelId"] == saved["modelId"]
    assert status["unreadableFiles"] == 1
    assert "broken.json" in status["unreadableExamples"][0]
