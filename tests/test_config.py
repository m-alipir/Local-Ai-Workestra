import pytest

from local_agent_orchestrator.core.config import load_models, load_settings


def test_settings_load():
    settings = load_settings()

    assert settings.orchestrator.task_retry_limit == 2
    assert settings.paths.runs == "runs"


def test_models_load():
    models = load_models()

    assert set(models.models) == {
        "qwen_coder",
        "gpt_oss",
        "bonsai2",
        "devstral",
    }
    assert models.models["qwen_coder"].role == "coder"
    assert models.models["bonsai2"].role == (
        "deep_reasoning_architecture_design_retrospective"
    )
    assert models.models["bonsai2"].flash_attention is True
    assert models.models["bonsai2"].model_path.endswith(
        "Ternary-Bonsai-2-27B-PQ2_0.gguf"
    )


def test_models_load_fails_closed_with_missing_runtime_entry(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text(
        "models:\n"
        "  qwen_coder:\n"
        "    role: coder\n"
        "    hf: test/model\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="missing required entries: bonsai2, devstral, gpt_oss",
    ):
        load_models(path)
