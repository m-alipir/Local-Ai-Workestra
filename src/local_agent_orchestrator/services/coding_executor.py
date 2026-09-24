from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from local_agent_orchestrator.agents.devstral_engineer import (
    DevstralEngineer,
)
from local_agent_orchestrator.agents.qwen_coder import QwenCoderAgent
from local_agent_orchestrator.core.config import load_models, load_settings
from local_agent_orchestrator.services.coding_context import (
    build_coding_context,
)
from local_agent_orchestrator.services.edit_operations import (
    apply_edit_operations,
    parse_edit_response,
)


CoderName = Literal["qwen_coder", "devstral"]


SYSTEM_PROMPT = (
    "You are a software implementation agent.\n\n"
    "Return ONLY valid JSON using exactly this schema:\n\n"
    "{\n"
    "  \"operations\": [\n"
    "    {\"kind\": \"replace_exact\", \"path\": \"...\", "
    "\"old_text\": \"...\", \"new_text\": \"...\"}\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- No markdown fences.\n"
    "- No explanation outside JSON.\n"
    "- replace_exact requires non-empty old_text and new_text; copy old_text exactly from evidence.\n"
    "- create_file requires complete content for the new file.\n"
    "- create_file content must not contain trailing spaces or tabs; blank lines must be empty.\n"
    "- delete_file requires only kind and path.\n"
    "- Modify only files required by the task.\n"
    "- Preserve unrelated existing code.\n"
    "- Never use absolute paths.\n"
    "- Never use ../ paths.\n"
    "- Use the repository exploration evidence as factual context.\n"
    "- Do not invent files, functions, APIs, or dependencies that were not observed.\n"
    "- For an existing file, use replace_exact with the exact old text observed in the evidence.\n"
    "- replace_exact must match exactly once; do not guess or use fuzzy matching.\n"
    "- If several requested changes affect one file, combine them into that single operation; include any unchanged lines between edits in the exact old_text/new_text span.\n"
    "- For a new file, use create_file with its workspace-relative path and complete content.\n"
    "- Use delete_file only when the task explicitly requires deleting an observed file.\n"
    "- Use one operation per path.\n"
)


def execute_coding_task(
    task: str,
    workspace_root: str | Path,
    *,
    coder: CoderName = "qwen_coder",
    context_callback: Callable[[str], None] | None = None,
    operation_callback: Callable[[list[dict]], None] | None = None,
    forbidden_scope: list[str] | None = None,
) -> list[str]:
    settings = load_settings()
    models = load_models()

    context = build_coding_context(
        task=task,
        workspace_root=str(workspace_root),
    )

    if context_callback is not None:
        context_callback(
            context.as_prompt()
        )

    model = models.models[coder]

    common = {
        "model": model,
        "minimum_free_ram_gb": settings.resources.minimum_free_ram_gb,
        "minimum_free_vram_gb": settings.resources.minimum_free_vram_gb,
        "start_timeout": settings.orchestrator.model_start_timeout,
        "stop_timeout": settings.orchestrator.model_stop_timeout,
    }

    if coder == "qwen_coder":
        agent = QwenCoderAgent(**common)
    elif coder == "devstral":
        agent = DevstralEngineer(**common)
    else:
        raise ValueError(
            f"Unsupported coder: {coder}"
        )

    prompt = (
        SYSTEM_PROMPT
        + "\n\n"
        + context.as_prompt()
    )

    if forbidden_scope:
        prompt += (
            "\n\nFORBIDDEN TASK SCOPE:\n"
            + "\n".join(f"- {path}" for path in forbidden_scope)
            + "\nThese are hard safety boundaries. Never modify them."
        )

    result = agent.run(prompt)

    operations = parse_edit_response(
        result.content
    )

    if operation_callback is not None:
        operation_callback([
            operation.model_dump(mode="json")
            for operation in operations.operations
        ])

    return apply_edit_operations(
        workspace_root,
        operations,
        grounded_paths=context.grounded_paths or None,
        forbidden_scope=forbidden_scope,
    )
