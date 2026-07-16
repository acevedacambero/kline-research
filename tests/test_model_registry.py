import json
from pathlib import Path

import pytest

from kline.model.registry import (
    MODEL_ACTIVATION_VERSION,
    MODEL_REGISTRY_VERSION,
    ModelPromotionError,
    ModelRegistry,
)


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


def test_model_registry_promotes_trained_model_and_keeps_rollback_history(tmp_path):
    registry = ModelRegistry(tmp_path)
    dependencies = {
        "scoreDefinitionVersion": "score-v1",
        "labelDefinitionVersion": "labels-v1",
    }
    first = registry.save(
        "baseline",
        {"version": "model-v1", "status": "trained", "labelColumn": "label"},
        dependencies=dependencies,
    )
    second = registry.save(
        "baseline",
        {
            "version": "model-v2",
            "status": "trained",
            "labelColumn": "label",
            "coefficient": 0.7,
        },
        dependencies=dependencies,
    )

    registry.promote(first["modelId"], expected_dependencies=dependencies)
    promoted = registry.promote(second["modelId"], expected_dependencies=dependencies)
    status = registry.list()

    assert status["activationVersion"] == MODEL_ACTIVATION_VERSION
    assert promoted["previousModelId"] == first["modelId"]
    assert status["activeModels"]["baseline"]["modelId"] == second["modelId"]
    assert next(item for item in status["artifacts"] if item["active"])["modelId"] == second["modelId"]
    activation = json.loads(registry.activation_path.read_text(encoding="utf-8"))
    assert [item["modelId"] for item in activation["history"]] == [
        first["modelId"],
        second["modelId"],
    ]


def test_model_registry_rejects_review_and_stale_dependency_models(tmp_path):
    registry = ModelRegistry(tmp_path)
    review = registry.save(
        "baseline",
        {"version": "model-v1", "status": "review"},
        dependencies={
            "scoreDefinitionVersion": "score-v1",
            "labelDefinitionVersion": "labels-v1",
        },
    )
    stale = registry.save(
        "baseline",
        {"version": "model-v1", "status": "trained"},
        dependencies={
            "scoreDefinitionVersion": "score-v0",
            "labelDefinitionVersion": "labels-v1",
        },
    )

    with pytest.raises(ModelPromotionError, match="只有训练通过") as review_error:
        registry.promote(
            review["modelId"],
            expected_dependencies={
                "scoreDefinitionVersion": "score-v1",
                "labelDefinitionVersion": "labels-v1",
            },
        )
    assert review_error.value.code == "MODEL_NOT_PROMOTABLE"

    with pytest.raises(ModelPromotionError, match="依赖版本已过期") as stale_error:
        registry.promote(
            stale["modelId"],
            expected_dependencies={
                "scoreDefinitionVersion": "score-v1",
                "labelDefinitionVersion": "labels-v1",
            },
        )
    assert stale_error.value.code == "MODEL_DEPENDENCY_MISMATCH"

    missing = registry.save(
        "multifeature",
        {"version": "model-v1", "status": "trained"},
        dependencies={
            "scoreDefinitionVersion": "score-v1",
            "labelDefinitionVersion": "labels-v1",
        },
    )
    with pytest.raises(ModelPromotionError, match="featureDefinitionVersion"):
        registry.promote(
            missing["modelId"],
            expected_dependencies={
                "scoreDefinitionVersion": "score-v1",
                "featureDefinitionVersion": "features-v1",
                "labelDefinitionVersion": "labels-v1",
            },
        )
