from __future__ import annotations

from local_agent_orchestrator.agents.gpt_oss_reviewer import GptOssReviewer
from local_agent_orchestrator.core.config import load_models, load_settings


def diagnose_failure(
    task: str,
    stdout: str,
    stderr: str,
    repo_context: str | None = None,
) -> str:
    settings = load_settings()
    models = load_models()

    model = models.models["gpt_oss"]

    reviewer = GptOssReviewer(
        model=model,
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
    )

    result = reviewer.diagnose(
        task=task,
        stdout=stdout,
        stderr=stderr,
        repo_context=repo_context,
    )

    diagnosis = result.content.strip()

    if diagnosis:
        return diagnosis

    failure = stderr.strip() or stdout.strip() or "unknown failure"

    return (
        "Reviewer produced no final diagnosis. "
        "Use the supplied repository evidence as authoritative. "
        "Do not invent repository paths or files. "
        f"Correct the previous failure directly: {failure}"
    )
