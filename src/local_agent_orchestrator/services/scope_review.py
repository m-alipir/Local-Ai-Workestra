from __future__ import annotations

import json
import subprocess
from pathlib import Path

from local_agent_orchestrator.agents.gpt_oss_reviewer import GptOssReviewer
from local_agent_orchestrator.core.config import load_models, load_settings
from local_agent_orchestrator.models.scope import ScopeReview
from local_agent_orchestrator.services.task_scope import classify_changed_files


MAX_SCOPE_DIFF_CHARS = 20_000


def _focused_diff(workspace_root: str | Path, paths: list[str]) -> str:
    if not paths:
        return "(no unexpected diff)"
    root = Path(workspace_root)
    parts: list[str] = []
    for path in paths:
        result = subprocess.run(
            [
                "git",
                "diff",
                "HEAD",
                "--no-ext-diff",
                "--unified=40",
                "--",
                path,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip()
                or "Could not collect the focused scope diff."
            )
        if result.stdout:
            parts.append(result.stdout)
            continue

        file_path = root / path
        if file_path.is_file():
            try:
                content = file_path.read_text()
            except OSError as exc:
                raise RuntimeError(
                    f"Could not read unexpected file {path}: {exc}"
                ) from exc
            parts.append(f"--- NEW FILE {path} ---\n{content}")

    return "\n".join(parts)[:MAX_SCOPE_DIFF_CHARS] or "(unexpected files have no readable diff)"


def _fail_hard(reason: str) -> ScopeReview:
    return ScopeReview(
        decision="FAIL_HARD",
        reason=reason,
        instruction="Do not preserve the unexpected changes.",
    )


def _parse_review(raw: object) -> ScopeReview:
    if isinstance(raw, ScopeReview):
        return raw
    content = getattr(raw, "content", raw)
    if not isinstance(content, str):
        return _fail_hard("Scope reviewer returned no structured decision.")
    try:
        return ScopeReview.model_validate(json.loads(content))
    except Exception as exc:
        return _fail_hard(f"Scope reviewer returned invalid JSON: {exc}")


def review_unexpected_scope(
    *,
    task: str,
    workspace_root: str | Path,
    changed_files: list[str],
    primary_scope: list[str],
    discouraged_scope: list[str],
    forbidden_scope: list[str],
) -> ScopeReview:
    classification = classify_changed_files(
        changed_files,
        primary_scope=primary_scope,
        discouraged_scope=discouraged_scope,
        forbidden_scope=forbidden_scope,
    )
    if classification.forbidden:
        return _fail_hard(
            "Forbidden scope change detected: "
            + ", ".join(classification.forbidden)
        )
    if not classification.grey:
        return ScopeReview(
            decision="PASS",
            reason="All changes are within primary scope.",
            preserve_paths=list(changed_files),
        )

    settings = load_settings()
    models = load_models()
    reviewer = GptOssReviewer(
        model=models.models["gpt_oss"],
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
    )
    try:
        result = reviewer.review_scope(
            task=task,
            changed_files=list(changed_files),
            primary_scope=list(primary_scope),
            discouraged_scope=list(discouraged_scope),
            forbidden_scope=list(forbidden_scope),
            diff_text=_focused_diff(workspace_root, list(classification.grey)),
        )
        review = _parse_review(result)
    except Exception as exc:
        return _fail_hard(f"Scope reviewer failed: {type(exc).__name__}: {exc}")

    changed = set(changed_files)
    referenced = set(review.preserve_paths) | set(review.remove_paths)
    if not referenced <= changed:
        return _fail_hard(
            "Scope reviewer referenced a path outside the changed-file set."
        )
    if review.decision == "REVISE" and not review.instruction.strip():
        return _fail_hard("Scope reviewer requested revision without guidance.")
    return review
