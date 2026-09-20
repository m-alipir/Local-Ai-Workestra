from unittest.mock import MagicMock, patch

from local_agent_orchestrator.agents.gpt_oss_reviewer import GptOssReviewer
from local_agent_orchestrator.models.config import ModelConfig
from local_agent_orchestrator.services.reviewer import diagnose_failure


def test_gpt_oss_reviewer_returns_diagnosis():
    model = ModelConfig(
        role="reviewer_optimizer",
        hf="test/model",
        context=8192,
        reasoning="medium",
    )

    fake_server = MagicMock()
    fake_server.chat.return_value = "Root cause: wrong comparison."

    context_manager = MagicMock()
    context_manager.__enter__.return_value = fake_server
    context_manager.__exit__.return_value = None

    with patch(
        "local_agent_orchestrator.agents.gpt_oss_reviewer.LlamaServer",
        return_value=context_manager,
    ):
        reviewer = GptOssReviewer(
            model=model,
            minimum_free_ram_gb=2.0,
            minimum_free_vram_gb=1.0,
        )

        result = reviewer.diagnose(
            task="Fix function",
            stdout="failed",
            stderr="AssertionError",
        )

    assert "Root cause" in result.content


def test_diagnose_failure_service():
    fake_reviewer = MagicMock()
    fake_reviewer.diagnose.return_value.content = "diagnosis"

    with patch(
        "local_agent_orchestrator.services.reviewer.GptOssReviewer",
        return_value=fake_reviewer,
    ):
        result = diagnose_failure(
            task="task",
            stdout="out",
            stderr="err",
        )

    assert result == "diagnosis"
