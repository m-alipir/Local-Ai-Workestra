from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_agent_orchestrator.agents.nemotron_retrospective import (
    NemotronRetrospective,
)
from local_agent_orchestrator.core.config import load_models, load_settings


_AUTHORITATIVE_EVENTS = {
    "verification_bootstrapped",
    "verification_baseline_finished",
    "coding_output_rejected",
    "verification_compared",
    "checkpoint_created",
    "checkpoint_failed",
    "task_completed",
}
_COMMENTARY_BUDGET = 4_000


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    return value if isinstance(value, dict) else None


def _collect_trajectory(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "trajectory.jsonl"
    if not path.is_file():
        return []

    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for line in lines:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict) and value.get("event") in _AUTHORITATIVE_EVENTS:
            events.append(value)
    return events


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "event",
        "model",
        "attempt",
        "passed",
        "failure_class",
        "verification_phase",
        "verification_classification",
        "failure_identities",
        "detail",
    )
    compact: dict[str, Any] = {}
    for key in fields:
        if key not in event or event[key] is None:
            continue
        value = event[key]
        if key == "detail" and isinstance(value, str) and len(value) > 600:
            value = value[:600] + "...[truncated]"
        compact[key] = value
    return compact


def _bounded_commentary(values: list[Any]) -> list[str]:
    result: list[str] = []
    remaining = _COMMENTARY_BUDGET
    for value in values:
        text = str(value)
        if remaining <= 0:
            break
        if len(text) > remaining:
            result.append(text[:remaining] + "...[truncated]")
            break
        result.append(text)
        remaining -= len(text)
    return result


def _failure_attribution(metrics: dict[str, Any]) -> tuple[str, str | None]:
    classification = metrics.get("verification_classification")
    baseline = metrics.get("baseline_failure_identities") or []
    post_change = metrics.get("post_change_failure_identities") or []

    if classification == "preexisting_failures_only":
        return (
            "pre-existing repository debt; not agent-caused",
            "pre-existing baseline failure(s): " + ", ".join(baseline),
        )
    if classification == "baseline_failures_disappeared":
        return (
            "pre-existing baseline failure(s) disappeared; no new failure recorded",
            "baseline failure(s) disappeared: " + ", ".join(baseline),
        )
    if classification == "new_failures":
        return (
            "new post-change failure identities recorded",
            "new post-change failure(s): " + ", ".join(post_change),
        )
    if classification == "passed" and metrics.get("passed") is True:
        return "none recorded", None
    return "unknown; not recorded", None


def _task_facts(
    metrics: dict[str, Any],
    task_status: str | None,
    events: list[dict[str, Any]],
    unknown: list[str],
) -> dict[str, Any]:
    task_id = str(metrics.get("task_id", "unknown"))
    task_events = [
        _compact_event(event)
        for event in events
        if event.get("task_id") in {None, task_id}
    ]
    bootstrap = [
        event for event in task_events
        if event.get("event") == "verification_bootstrapped"
    ]
    checkpoint_events = [
        event for event in task_events
        if event.get("event") in {"checkpoint_created", "checkpoint_failed"}
    ]
    operation_failures = metrics.get("operation_failures") or []
    if not operation_failures:
        operation_failures = [
            {
                "model": event.get("model"),
                "attempt": event.get("attempt"),
                "failure_class": event.get("failure_class"),
                "detail": event.get("detail"),
            }
            for event in task_events
            if event.get("event") == "coding_output_rejected"
            and event.get("failure_class")
        ]

    attribution, observation = _failure_attribution(metrics)
    if task_status is None:
        unknown.append(f"{task_id}.task_status")
    if metrics.get("verification_classification") is None:
        unknown.append(f"{task_id}.verification_classification")
    if metrics.get("baseline_returncode") is None:
        unknown.append(f"{task_id}.baseline_result")
    if not bootstrap:
        unknown.append(f"{task_id}.bootstrap_result")
    if operation_failures and not any(
        event.get("event") == "rollback" for event in task_events
    ):
        unknown.append(f"{task_id}.rollback_event")

    return {
        "task_id": task_id,
        "task_status": task_status or "unknown",
        "description": metrics.get("description"),
        "passed": metrics.get("passed"),
        "accepted_model": metrics.get("accepted_model"),
        "accepted_attempt": metrics.get("accepted_attempt"),
        "attempts": metrics.get("attempts"),
        "changed_files": metrics.get("changed_files", []),
        "commit": metrics.get("commit"),
        "bootstrap_events": bootstrap,
        "baseline": {
            "returncode": metrics.get("baseline_returncode"),
            "passed": metrics.get("baseline_passed"),
            "failure_identities": metrics.get(
                "baseline_failure_identities",
                [],
            ),
        },
        "post_change": {
            "returncode": metrics.get("test_returncode"),
            "failure_identities": metrics.get(
                "post_change_failure_identities",
                [],
            ),
        },
        "verification_classification": metrics.get(
            "verification_classification"
        ),
        "failure_attribution": attribution,
        "observed_failure": observation,
        "operation_failures": operation_failures,
        "checkpoint_events": checkpoint_events,
        "trajectory_events": task_events,
    }


def build_retrospective_context(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    metrics = collect_run_metrics(root)
    state = _read_json(root / "state.json")
    events = _collect_trajectory(root)
    unknown: list[str] = []

    raw_state_tasks = (state or {}).get("tasks", [])
    if not isinstance(raw_state_tasks, list):
        raw_state_tasks = []
        unknown.append("run.tasks")
    state_tasks = {
        str(task.get("id")): task.get("status")
        for task in raw_state_tasks
        if isinstance(task, dict) and task.get("id") is not None
    }
    if state is None:
        unknown.append("run.status")

    task_facts = [
        _task_facts(
            metric,
            state_tasks.get(str(metric.get("task_id"))),
            events,
            unknown,
        )
        for metric in metrics
    ]

    commentary = {
        "reviewer_diagnoses": _bounded_commentary([
            diagnosis
            for metric in metrics
            for diagnosis in metric.get("diagnoses", [])
        ]),
        "security_reviews": _bounded_commentary([
            metric.get("security_review")
            for metric in metrics
            if metric.get("security_review") is not None
        ]),
        "optimization_reviews": _bounded_commentary([
            metric.get("optimization_review")
            for metric in metrics
            if metric.get("optimization_review") is not None
        ]),
    }

    return {
        "authoritative_facts": {
            "run_status": (state or {}).get("status", "unknown"),
            "tasks": task_facts,
        },
        "lower_authority_commentary": commentary,
        "unknown": sorted(set(unknown)),
    }


def _observed_failure_text(context: dict[str, Any]) -> str:
    observations = [
        task["observed_failure"]
        for task in context["authoritative_facts"]["tasks"]
        if task.get("observed_failure")
    ]
    if not observations:
        return "None recorded."
    return "\n".join(f"- {observation}" for observation in observations)


def _suggestion_text(context: dict[str, Any]) -> str:
    tasks = context["authoritative_facts"]["tasks"]
    suggestions: list[str] = []
    for task in tasks:
        checkpoint_failures = [
            event for event in task["checkpoint_events"]
            if event.get("event") == "checkpoint_failed"
        ]
        if checkpoint_failures:
            suggestions.append(
                f"{task['task_id']}: review the recorded checkpoint failure before retrying."
            )
            continue
        failure_classes = sorted({
            str(failure.get("failure_class"))
            for failure in task["operation_failures"]
            if failure.get("failure_class")
        })
        if failure_classes:
            suggestions.append(
                f"{task['task_id']}: address recorded operation failure classes: "
                + ", ".join(failure_classes)
                + "."
            )
            continue
        if task["verification_classification"] in {
            "preexisting_failures_only",
            "baseline_failures_disappeared",
        }:
            suggestions.append(
                f"{task['task_id']}: treat the baseline-only failure as unrelated "
                "pre-existing repository debt; do not attribute it to this task."
            )
            continue
        if task["passed"] is True and task["operation_failures"] == []:
            suggestions.append(
                f"{task['task_id']}: no corrective action recorded."
            )
            continue
        suggestions.append(
            f"{task['task_id']}: no suggestion; relevant evidence is unknown."
        )
    return "\n".join(suggestions) or "No suggestion; no task facts were recorded."


def collect_run_metrics(run_dir: str | Path) -> list[dict]:
    metrics_dir = Path(run_dir) / "metrics"

    if not metrics_dir.exists():
        return []

    results: list[dict] = []

    for path in sorted(metrics_dir.glob("*.json")):
        results.append(
            json.loads(path.read_text(encoding="utf-8"))
        )

    return results


def generate_retrospective(
    run_dir: str | Path,
) -> Path:
    settings = load_settings()
    models = load_models()

    context = build_retrospective_context(run_dir)
    context_json = json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )

    # The existing retrospective interface is model-agnostic; active routing
    # supplies Bonsai 2 through the trusted model configuration.
    reviewer = NemotronRetrospective(
        model=models.models["bonsai2"],
        minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
        minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
        start_timeout=settings.orchestrator.model_start_timeout,
        stop_timeout=settings.orchestrator.model_stop_timeout,
    )

    result = reviewer.run(
        context_json,
    )

    content = (
        "AUTHORITATIVE FACTS:\n"
        + context_json
        + "\n\nOBSERVED FAILURE:\n"
        + _observed_failure_text(context)
        + "\n\nMODEL COMMENTARY (UNVERIFIED):\n"
        + result.content.strip()
        + "\n\nSUGGESTION:\n"
        + _suggestion_text(context)
        + "\n"
    )
    path = Path(run_dir) / "retrospective.md"
    path.write_text(content, encoding="utf-8")

    return path
