from unittest.mock import MagicMock, patch

from local_agent_orchestrator.agents.nemotron_retrospective import (
    NemotronRetrospective,
)
from local_agent_orchestrator.models.config import ModelConfig


def test_retrospective_forwards_configured_local_bonsai_server():
    model = ModelConfig(
        role="deep_reasoning_architecture_design_retrospective",
        hf="local/bonsai",
        binary="/opt/bonsai/llama-server",
        model_path="/opt/bonsai/model.gguf",
        flash_attention=True,
        reasoning="high",
    )
    fake_server = MagicMock()
    fake_server.chat.return_value = "retrospective"
    context_manager = MagicMock()
    context_manager.__enter__.return_value = fake_server
    context_manager.__exit__.return_value = None

    with patch(
        "local_agent_orchestrator.agents.nemotron_retrospective.LlamaServer",
        return_value=context_manager,
    ) as server_class:
        result = NemotronRetrospective(
            model=model,
            minimum_free_ram_gb=1.0,
            minimum_free_vram_gb=1.0,
        ).run("{}")

    assert result.content == "retrospective"
    assert server_class.call_args.kwargs["binary"] == "/opt/bonsai/llama-server"
    assert server_class.call_args.kwargs["model_path"] == "/opt/bonsai/model.gguf"
    assert server_class.call_args.kwargs["flash_attention"] is True
