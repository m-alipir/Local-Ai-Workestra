from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.models.config import ModelConfig


@dataclass(slots=True)
class RetrospectiveResult:
    content: str


class NemotronRetrospective:
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

    def run(self, metrics_json: str) -> RetrospectiveResult:
        system_prompt = """You are an engineering retrospective agent.

Analyze only the supplied retrospective context. It contains two trust levels:
AUTHORITATIVE_FACTS are system-recorded execution facts and must never be
contradicted. LOWER_AUTHORITY_COMMENTARY contains reviewer/model text and is
unverified; never convert it into a repository fact.

Return a short retrospective with exactly these sections:
STRONG:
WEAK:
WASTE:
RECOMMENDATION:
REASONING_ADJUSTMENT:

Rules:
- Do not invent metrics, failures, files, causes, or recommendations.
- Treat baseline-only failures as unrelated pre-existing repository debt; never
  describe them as introduced by the agent or recommend fixing them as part of
  the completed task.
- For a successful first attempt with no operation failures, do not invent
  failure analysis.
- Discuss a failed operation only when its recorded failure_class is present.
- Discuss checkpoint failure only when a checkpoint_failed event is present.
- If a condition is absent or unrecorded, say it is unknown.
- Prefer concrete repeated patterns.
- Mention unnecessary retries or reviewer calls.
- Recommend routing/reasoning changes only when supported by evidence.
- Keep it concise.
"""

        with LlamaServer(
            hf_model=self.model.hf,
            context=self.model.context,
            binary=self.model.binary or "~/llama.cpp/build/bin/llama-server",
            model_path=self.model.model_path,
            flash_attention=self.model.flash_attention,
            minimum_free_ram_gb=self.minimum_free_ram_gb,
            minimum_free_vram_gb=self.minimum_free_vram_gb,
            start_timeout=self.start_timeout,
            stop_timeout=self.stop_timeout,
            reasoning=self.model.reasoning,
        ) as server:
            content = server.chat(
                prompt=metrics_json,
                system_prompt=system_prompt,
                max_tokens=1536,
                temperature=0.1,
            )

        return RetrospectiveResult(content=content)
