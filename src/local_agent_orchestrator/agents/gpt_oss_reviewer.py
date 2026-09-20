from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.models.config import ModelConfig


@dataclass(slots=True)
class ReviewResult:
    content: str


class GptOssReviewer:
    def __init__(
        self,
        model: ModelConfig,
        minimum_free_ram_gb: float,
        minimum_free_vram_gb: float,
        start_timeout: int = 120,
        stop_timeout: int = 20,
    ) -> None:
        self.model = model
        self.minimum_free_ram_gb = minimum_free_ram_gb
        self.minimum_free_vram_gb = minimum_free_vram_gb
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout

    def diagnose(
        self,
        task: str,
        stdout: str,
        stderr: str,
        repo_context: str | None = None,
    ) -> ReviewResult:
        system_prompt = (
            "You are a software debugging reviewer. "
            "Analyze the failed implementation and test output. "
            "Identify the likely root cause and provide a concise, "
            "actionable fix plan for another coding agent. "
            "Do not write the full implementation unless necessary. "
            "Treat repository evidence as authoritative. "
            "Never claim that a file, directory, function, package, or API "
            "exists unless it appears in the supplied repository evidence. "
            "If evidence is insufficient, state that explicitly instead of guessing."
        )

        prompt = (
            f"TASK:\n{task}\n\n"
            f"TEST STDOUT:\n{stdout}\n\n"
            f"TEST STDERR:\n{stderr}\n"
        )

        with LlamaServer(
            hf_model=self.model.hf,
            context=self.model.context,
            minimum_free_ram_gb=self.minimum_free_ram_gb,
            minimum_free_vram_gb=self.minimum_free_vram_gb,
            start_timeout=self.start_timeout,
            stop_timeout=self.stop_timeout,
            reasoning=self.model.reasoning,
        ) as server:
            content = server.chat(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=1536,
                temperature=0.1,
            )

        return ReviewResult(content=content)
