from unittest.mock import MagicMock, patch

from local_agent_orchestrator.agents.repo_explorer import QwenRepoExplorer
from local_agent_orchestrator.models.config import ModelConfig


def test_repo_explorer_forwards_json_schema_response_format():
    model = ModelConfig(
        role="coder",
        hf="test/model",
        context=8192,
        reasoning="none",
    )
    fake_server = MagicMock()
    fake_server.chat.return_value = '{"type":"final","summary":"done"}'

    with patch(
        "local_agent_orchestrator.agents.repo_explorer.LlamaServer",
        return_value=fake_server,
    ):
        explorer = QwenRepoExplorer(model)
        explorer.run_step("Inspect repo", "evidence")

    response_format = fake_server.chat.call_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["required"] == ["type"]
