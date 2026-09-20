from __future__ import annotations

import json
import re
from dataclasses import dataclass

from local_agent_orchestrator.agents.repo_explorer import QwenRepoExplorer
from local_agent_orchestrator.core.config import (
    load_models,
    load_settings,
)
from local_agent_orchestrator.models.tool_action import ToolAction
from local_agent_orchestrator.services.repo_tools import RepoTools


# Keep deterministic bootstrap evidence within Qwen's 8,192-token context
# alongside the explorer prompt and any tool observations.
MAX_OBSERVATION_CHARS = 6_000
MAX_TRANSCRIPT_CHARS = 6_000
BOOTSTRAP_FILE_LIMIT = 80
BOOTSTRAP_CHARS = 3_000


class RepoExplorationError(RuntimeError):
    pass


@dataclass(slots=True)
class ExplorationResult:
    summary: str
    steps: int
    transcript: str
    observed_paths: tuple[str, ...] = ()


def _parse_response(content: str) -> dict:
    content = content.strip()

    start = content.find("{")
    if start == -1:
        raise RepoExplorationError(
            "Explorer did not return JSON."
        )

    try:
        value, _ = json.JSONDecoder().raw_decode(
            content[start:]
        )
    except json.JSONDecodeError as exc:
        raise RepoExplorationError(
            f"Invalid explorer JSON: {exc}"
        ) from exc

    if not isinstance(value, dict):
        raise RepoExplorationError(
            "Explorer response must be an object."
        )

    return value


def _trim_transcript(parts: list[str]) -> str:
    transcript = "\n\n".join(parts)

    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[
            -MAX_TRANSCRIPT_CHARS:
        ]

    return transcript


def _final_result(
    response: dict,
    *,
    steps: int,
    transcript: str,
    observed_paths: set[str],
) -> ExplorationResult:
    summary = response.get("summary")

    if not isinstance(summary, str) or not summary.strip():
        raise RepoExplorationError(
            "Final exploration response has no summary."
        )

    return ExplorationResult(
        summary=summary.strip(),
        steps=steps,
        transcript=transcript,
        observed_paths=tuple(sorted(observed_paths)),
    )


def _build_bootstrap_evidence(tools: RepoTools) -> tuple[str, set[str]]:
    files = tools.list_files(
        ".",
        max_results=BOOTSTRAP_FILE_LIMIT,
    )

    try:
        git_status = tools.git_status()
    except Exception as exc:
        git_status = f"(unavailable: {exc})"

    evidence = (
        "SYSTEM BOOTSTRAP REPOSITORY EVIDENCE:\n"
        "The following data was collected directly from the workspace "
        "before model reasoning. Treat it as authoritative.\n\n"
        "REPOSITORY FILES:\n"
        + (files or "(no files found)")
        + "\n\nGIT STATUS:\n"
        + (git_status or "(clean)")
    )

    if len(evidence) > BOOTSTRAP_CHARS:
        evidence = (
            evidence[:BOOTSTRAP_CHARS]
            + "\n...[bootstrap truncated]"
        )

    return evidence, {
        path.strip()
        for path in files.splitlines()
        if path.strip()
    }


def _observed_paths(action: ToolAction, content: str) -> set[str]:
    paths: set[str] = set()

    if action.tool == "read_file" and action.path:
        paths.add(action.path)
    elif action.tool in {"list_files", "git_diff"}:
        paths.update(
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.startswith("(")
        )
    elif action.tool == "search_text":
        for line in content.splitlines():
            match = re.match(r"^(.+?):\d+: ", line)
            if match:
                paths.add(match.group(1))

    return paths

def explore_repository(
    task: str,
    workspace_root: str,
    *,
    max_steps: int = 16,
) -> ExplorationResult:
    settings = load_settings()
    models = load_models()

    agent = QwenRepoExplorer(
        models.models["qwen_coder"],
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
    )

    tools = RepoTools(workspace_root)
    bootstrap_evidence, grounded_paths = _build_bootstrap_evidence(tools)
    transcript_parts: list[str] = [bootstrap_evidence]

    last_action_key: str | None = None
    repeated_action_count = 0

    agent.start()

    try:
        for step in range(1, max_steps + 1):
            transcript = _trim_transcript(
                transcript_parts
            )

            raw = agent.run_step(
                task=task,
                transcript=transcript,
            )

            response = _parse_response(raw)
            response_type = response.get("type")

            direct_tool_types = {
                "list_files",
                "search_text",
                "read_file",
                "git_status",
                "git_diff",
            }

            if response_type is None and response.get("tool") in direct_tool_types:
                response = {
                    **response,
                    "type": "tool",
                }
                response_type = "tool"

            if response_type in direct_tool_types:
                response = {
                    **response,
                    "type": "tool",
                    "tool": response_type,
                }
                response_type = "tool"

            if response_type == "final":
                return _final_result(
                    response,
                    steps=step,
                    transcript=transcript,
                    observed_paths=grounded_paths,
                )

            if response_type != "tool":
                raise RepoExplorationError(
                    f"Unknown explorer response type: {response_type}"
                )

            try:
                action = ToolAction(
                    tool=response.get("tool"),
                    path=response.get("path"),
                    query=response.get("query"),
                    max_results=response.get(
                        "max_results",
                        50,
                    ),
                )
            except Exception as exc:
                raise RepoExplorationError(
                    f"Invalid tool action: {exc}"
                ) from exc

            action_key = json.dumps(
                action.model_dump(),
                sort_keys=True,
                ensure_ascii=False,
            )

            if action_key == last_action_key:
                repeated_action_count += 1
            else:
                repeated_action_count = 0
                last_action_key = action_key

            if repeated_action_count >= 1:
                transcript_parts.append(
                    "ACTION:\n"
                    + json.dumps(
                        action.model_dump(),
                        ensure_ascii=False,
                    )
                    + "\nOBSERVATION:\n"
                    + "This exact tool action was already performed. "
                    + "Do not repeat it. Use a different targeted action "
                    + "or return a final summary."
                )
                continue

            observation = tools.execute(action)
            observation_content = observation.content

            if observation.ok:
                grounded_paths.update(
                    _observed_paths(action, observation_content)
                )

            if len(observation_content) > MAX_OBSERVATION_CHARS:
                observation_content = (
                    observation_content[
                        :MAX_OBSERVATION_CHARS
                    ]
                    + "\n...[truncated]"
                )

            transcript_parts.append(
                "ACTION:\n"
                + json.dumps(
                    action.model_dump(),
                    ensure_ascii=False,
                )
                + "\nOBSERVATION:\n"
                + observation_content
            )

        transcript_parts.append(
            "SYSTEM NOTICE:\n"
            "The repository exploration budget is exhausted. "
            "Return type=final now using only evidence already observed. "
            "Do not request another tool."
        )

        transcript = _trim_transcript(
            transcript_parts
        )

        raw = agent.run_step(
            task=task,
            transcript=transcript,
        )

        response = _parse_response(raw)

        if response.get("type") != "final":
            raise RepoExplorationError(
                "Explorer did not return a final summary after "
                "the exploration budget was exhausted."
            )

        return _final_result(
            response,
            steps=max_steps + 1,
            transcript=transcript,
            observed_paths=grounded_paths,
        )

    finally:
        agent.stop()
