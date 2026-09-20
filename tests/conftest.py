import pytest

from local_agent_orchestrator.adapters import llama_server


@pytest.fixture(autouse=True)
def block_real_llm(monkeypatch):
    def blocked_start(self):
        raise RuntimeError(
            "Real LLM execution is forbidden in unit tests. Mock LlamaServer instead."
        )

    monkeypatch.setattr(
        llama_server.LlamaServer,
        "start",
        blocked_start,
    )
