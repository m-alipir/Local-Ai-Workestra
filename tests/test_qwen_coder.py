from unittest.mock import MagicMock, patch

from local_agent_orchestrator.agents.qwen_coder import QwenCoderAgent
from local_agent_orchestrator.models.config import ModelConfig


def test_qwen_coder_returns_result():
    model = ModelConfig(
        role="coder",
        hf="test/model",
        context=8192,
        reasoning="medium",
    )

    fake_server = MagicMock()
    fake_server.chat.return_value = "implementation"

    context_manager = MagicMock()
    context_manager.__enter__.return_value = fake_server
    context_manager.__exit__.return_value = None

    with patch(
        "local_agent_orchestrator.agents.qwen_coder.LlamaServer",
        return_value=context_manager,
    ):
        agent = QwenCoderAgent(
            model=model,
            minimum_free_ram_gb=2.0,
            minimum_free_vram_gb=1.0,
        )

        result = agent.run("Create a hello world function.")

    assert result.content == "implementation"
    fake_server.chat.assert_called_once()
    response_format = fake_server.chat.call_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert schema["required"] == ["operations"]
    alternatives = schema["properties"]["operations"]["items"]["oneOf"]
    assert len(alternatives) == 3
    by_kind = {
        alternative["properties"]["kind"]["enum"][0]: alternative
        for alternative in alternatives
    }
    assert by_kind["replace_exact"]["required"] == [
        "kind",
        "path",
        "old_text",
        "new_text",
    ]
    assert by_kind["replace_exact"]["properties"]["old_text"]["minLength"] == 1
    assert by_kind["create_file"]["required"] == [
        "kind",
        "path",
        "content",
    ]
    assert by_kind["delete_file"]["required"] == ["kind", "path"]
