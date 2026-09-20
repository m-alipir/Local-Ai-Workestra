from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.models.config import ModelConfig
from local_agent_orchestrator.models.edit import EDIT_RESPONSE_FORMAT


RESPONSE_FORMAT = EDIT_RESPONSE_FORMAT


@dataclass(slots=True)
class EngineeringResult:
    content: str


class DevstralEngineer:
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

    def run(self, task: str) -> EngineeringResult:
        system_prompt = (
            "You are the fallback software engineer. "
            "The primary implementation agent has already failed. "
            "Use the supplied repository evidence and failure context carefully. "
            "Prefer a minimal corrective implementation. "
            "Do not invent APIs, files, or dependencies."
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
                prompt=task,
                system_prompt=system_prompt,
                max_tokens=2048,
                temperature=0.15,
                response_format=RESPONSE_FORMAT,
            )

        return EngineeringResult(content=content)
