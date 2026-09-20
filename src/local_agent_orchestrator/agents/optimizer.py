from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.models.config import ModelConfig


@dataclass(slots=True)
class OptimizationReviewResult:
    content: str


class OptimizerAgent:
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

    def review(
        self,
        task: str,
        files: dict[str, str],
    ) -> OptimizationReviewResult:
        system_prompt = """You are a software performance reviewer.

Return concise findings only.

Rules:
- Do not suggest speculative optimization.
- Prefer measurable bottlenecks.
- Focus on N+1 queries, repeated I/O, unnecessary network calls,
  duplicate computation, poor batching, excessive serialization,
  blocking operations, memory waste, cache misuse, and algorithmic issues.
- Every suggested optimization must include what should be measured
  before and after.
- If there is no meaningful performance concern, say so clearly.
"""

        file_text = ""

        for path, content in files.items():
            file_text += (
                f"\n--- FILE: {path} ---\n"
                f"{content}\n"
            )

        prompt = (
            f"TASK:\n{task}\n\n"
            f"CHANGED FILE CONTENTS:\n{file_text}"
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

        return OptimizationReviewResult(content=content)
