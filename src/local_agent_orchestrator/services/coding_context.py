from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.services.repo_explorer import (
    ExplorationResult,
    explore_repository,
)


MAX_EXPLORATION_CONTEXT_CHARS = 6_000


@dataclass(slots=True)
class CodingContext:
    task: str
    exploration_summary: str
    exploration_transcript: str
    grounded_paths: tuple[str, ...] = ()

    def as_prompt(self) -> str:
        transcript = self.exploration_transcript

        if len(transcript) > MAX_EXPLORATION_CONTEXT_CHARS:
            transcript = (
                transcript[-MAX_EXPLORATION_CONTEXT_CHARS:]
            )

        return f"""TASK:
{self.task}

REPOSITORY EXPLORATION SUMMARY:
{self.exploration_summary}

REPOSITORY EVIDENCE:
{transcript or '(no tool observations recorded)'}

AUTHORITATIVE OBSERVED PATHS:
{chr(10).join(self.grounded_paths) or '(none recorded)'}

Use the repository evidence above as factual context.
Do not invent files, APIs, functions, or behavior that were not observed.
For replace_exact and delete_file, use only an observed existing path.
Copy replace_exact.old_text as one exact contiguous excerpt from the evidence;
if the exact excerpt is not present, do not guess it.
For create_file, use a new workspace-relative path and provide complete content.
New-file content must not contain trailing spaces or tabs; blank lines must be
empty. Preserve meaningful whitespace in the file rather than guessing or
normalizing it.
"""


def build_coding_context(
    task: str,
    workspace_root: str,
    *,
    max_exploration_steps: int = 16,
) -> CodingContext:
    exploration: ExplorationResult = explore_repository(
        task=task,
        workspace_root=workspace_root,
        max_steps=max_exploration_steps,
    )

    return CodingContext(
        task=task,
        exploration_summary=exploration.summary,
        exploration_transcript=exploration.transcript,
        grounded_paths=exploration.observed_paths,
    )
