from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from local_agent_orchestrator.agents.security_reviewer import SecurityReviewer
from local_agent_orchestrator.core.config import load_models, load_settings
from local_agent_orchestrator.models.security import SecurityReview
from local_agent_orchestrator.services.workspace import Workspace


SECURITY_KEYWORDS = (
    "auth",
    "authentication",
    "authorization",
    "login",
    "logout",
    "password",
    "credential",
    "secret",
    "token",
    "api key",
    "oauth",
    "jwt",
    "session",
    "cookie",
    "permission",
    "privilege",
    "role",
    "admin",
    "csrf",
    "cors",
    "webhook",
    "upload",
    "user input",
    "sql",
    "database query",
    "shell",
    "subprocess",
    "command execution",
    "encryption",
    "cryptography",
    "llm tool",
    "agent permission",
)

SECURITY_PATH_MARKERS = (
    "auth",
    "security",
    "login",
    "oauth",
    "session",
    "permission",
    "credential",
    "secret",
    "token",
    "admin",
    "middleware",
    "webhook",
)


def _contains_security_keyword(text: str) -> bool:
    lowered = text.lower()

    for keyword in SECURITY_KEYWORDS:
        pattern = (
            r"(?<![a-z0-9_])"
            + re.escape(keyword)
            + r"(?![a-z0-9_])"
        )

        if re.search(pattern, lowered):
            return True

    return False


def requires_security_review(
    task: str,
    changed_files: list[str],
) -> bool:
    if _contains_security_keyword(task):
        return True

    for path in changed_files:
        lowered = path.lower()

        if any(
            marker in lowered
            for marker in SECURITY_PATH_MARKERS
        ):
            return True

    return False


def parse_security_review(text: str) -> SecurityReview:
    cleaned = text.strip()
    start = cleaned.find("{")

    if start == -1:
        raise ValueError(
            "Security reviewer returned no JSON object."
        )

    data, _ = json.JSONDecoder().raw_decode(
        cleaned[start:]
    )

    return SecurityReview.model_validate(data)


def _git_diff(
    workspace_root: str | Path,
    revision: str | None = None,
) -> str:
    command = [
        "git",
        "diff",
        "--no-ext-diff",
        "--unified=40",
    ]
    if revision:
        command.extend([f"{revision}^", revision])

    result = subprocess.run(
        command,
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Could not collect the Git diff for security review."
        )

    return result.stdout[:50000]


def run_security_review(
    task: str,
    changed_files: list[str],
    workspace_root: str | Path,
    revision: str | None = None,
) -> SecurityReview:
    settings = load_settings()
    models = load_models()
    workspace = Workspace(workspace_root)

    files: dict[str, str] = {}

    for path in changed_files:
        if workspace.exists(path):
            files[path] = workspace.read_text(path)

    model = models.models["gpt_oss"]

    reviewer = SecurityReviewer(
        model=model,
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
    )

    result = reviewer.review(
        task=task,
        files=files,
        diff_text=_git_diff(workspace_root, revision=revision),
    )

    return parse_security_review(
        result.content
    )
