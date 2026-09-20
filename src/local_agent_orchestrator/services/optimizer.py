from __future__ import annotations

from pathlib import Path

from local_agent_orchestrator.agents.optimizer import OptimizerAgent
from local_agent_orchestrator.core.config import load_models, load_settings
from local_agent_orchestrator.services.workspace import Workspace


PERFORMANCE_KEYWORDS = (
    "performance",
    "optimize",
    "optimization",
    "latency",
    "throughput",
    "bottleneck",
    "slow query",
    "n+1",
    "query count",
    "batching",
    "cache performance",
    "memory usage",
    "cpu usage",
    "network latency",
    "api latency",
    "database performance",
    "vector search performance",
    "cold start",
)



def requires_optimization_review(
    task: str,
    changed_files: list[str],
) -> bool:
    text = (task + "\n" + "\n".join(changed_files)).lower()

    return any(
        keyword in text
        for keyword in PERFORMANCE_KEYWORDS
    )


def run_optimization_review(
    task: str,
    changed_files: list[str],
    workspace_root: str | Path,
) -> str:
    settings = load_settings()
    models = load_models()
    workspace = Workspace(workspace_root)

    files: dict[str, str] = {}

    for path in changed_files:
        if workspace.exists(path):
            files[path] = workspace.read_text(path)

    reviewer = OptimizerAgent(
        model=models.models["gpt_oss"],
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
    )

    result = reviewer.review(
        task=task,
        files=files,
    )

    return result.content
