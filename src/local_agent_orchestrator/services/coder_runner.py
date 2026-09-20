from __future__ import annotations

from local_agent_orchestrator.agents.qwen_coder import QwenCoderAgent
from local_agent_orchestrator.core.config import load_models, load_settings


def run_qwen_coder(task: str) -> str:
    settings = load_settings()
    models = load_models()

    model = models.models["qwen_coder"]

    agent = QwenCoderAgent(
        model=model,
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
    )

    result = agent.run(task)
    return result.content
