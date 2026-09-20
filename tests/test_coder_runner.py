from unittest.mock import MagicMock, patch

from local_agent_orchestrator.services.coder_runner import run_qwen_coder


def test_run_qwen_coder():
    fake_agent = MagicMock()
    fake_agent.run.return_value.content = "done"

    with patch(
        "local_agent_orchestrator.services.coder_runner.QwenCoderAgent",
        return_value=fake_agent,
    ):
        result = run_qwen_coder("test task")

    assert result == "done"
    fake_agent.run.assert_called_once_with("test task")
