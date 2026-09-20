from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.models.config import ModelConfig


@dataclass(slots=True)
class SecurityReviewResult:
    content: str


class SecurityReviewer:
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
        diff_text: str = "",
    ) -> SecurityReviewResult:
        system_prompt = """You are a security-focused software reviewer.

Return ONLY valid JSON:

{
  "findings": [
    {
      "severity": "low|medium|high|critical",
      "title": "short title",
      "description": "concrete risk",
      "recommendation": "specific fix"
    }
  ]
}

Rules:
- No markdown.
- No explanation outside JSON.
- Review the actual supplied code.
- Treat the git diff as the primary evidence of what changed.
- Use full file contents only to understand surrounding context.
- Do not invent vulnerabilities.
- Use high or critical only for concrete severe risks.
- Return {"findings": []} when no concrete issue exists.
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
                max_tokens=2048,
                temperature=0.1,
            )

        return SecurityReviewResult(content=content)
