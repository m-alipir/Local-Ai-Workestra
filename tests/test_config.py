import pytest

from local_agent_orchestrator.core.config import load_models, load_settings


def test_settings_load():
    settings = load_settings()

    assert settings.orchestrator.task_retry_limit == 2
    assert settings.paths.runs == "runs"


def test_models_load():
    models = load_models()

    assert "qwen_coder" in models.models
    assert models.models["qwen_coder"].role == "coder"


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
        match="missing required entries: devstral, gpt_oss, nemotron, qwen_general",
    ):
        load_models(path)
