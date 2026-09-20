from __future__ import annotations

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.models.config import ModelConfig


SYSTEM_PROMPT = """You are a repository exploration agent.

Your job is to understand enough of the repository to prepare for a coding task.

You have read-only tools:
- list_files
- search_text
- read_file
- git_status
- git_diff

Return exactly one JSON object and nothing else.

To call a tool:
{
  "type": "tool",
  "tool": "search_text",
  "path": null,
  "query": "example",
  "max_results": 50
}

When you have enough information:
{
  "type": "final",
  "summary": "Concise repository context relevant to the task."
}

Rules:
- Inspect before concluding.
- Prefer targeted search over reading many unrelated files.
- Never invent repository contents.
- Do not request write operations.
- Stay inside the repository.
- Keep the final summary factual and implementation-relevant.
"""


RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "repository_exploration_action",
        "schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["tool", "final"],
                },
                "tool": {"type": "string"},
                "path": {"type": "string"},
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "summary": {"type": "string"},
            },
            "required": ["type"],
            "additionalProperties": False,
        },
    },
}


class QwenRepoExplorer:
    def __init__(
        self,
        model: ModelConfig,
        *,
        start_timeout: int = 120,
        stop_timeout: int = 20,
        minimum_free_ram_gb: float = 2.0,
        minimum_free_vram_gb: float = 1.0,
    ):
        self.server = LlamaServer(
            hf_model=model.hf,
            context=model.context,
            start_timeout=start_timeout,
            stop_timeout=stop_timeout,
            minimum_free_ram_gb=minimum_free_ram_gb,
            minimum_free_vram_gb=minimum_free_vram_gb,
            reasoning=model.reasoning,
        )

    def start(self) -> None:
        self.server.start()

    def stop(self) -> None:
        self.server.stop()

    def run_step(
        self,
        task: str,
        transcript: str,
    ) -> str:
        prompt = f"""TASK:
{task}

EXPLORATION SO FAR:
{transcript or '(none yet)'}

Choose the next read-only tool action, or return a final summary if you have enough context.
"""

        return self.server.chat(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.1,
            response_format=RESPONSE_FORMAT,
        )
