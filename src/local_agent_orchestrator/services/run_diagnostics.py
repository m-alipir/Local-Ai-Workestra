from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any


DEFAULT_MAX_TEXT_CHARS = 2_000
DEFAULT_MAX_EVENTS = 100
DEFAULT_MAX_ARTIFACTS = 100


def collect_run_diagnostics(
    run_dir: str | Path,
    *,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
    max_events: int = DEFAULT_MAX_EVENTS,
    max_artifacts: int = DEFAULT_MAX_ARTIFACTS,
) -> dict[str, Any]:
    """Read durable run evidence into a bounded, deterministic summary."""
    if max_text_chars < 0 or max_events < 0 or max_artifacts < 0:
        raise ValueError("Diagnostic limits must be non-negative.")

    root = Path(run_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Run directory not found: {root}")

    source_errors: list[str] = []
    state = _read_object(root / "state.json", source_errors)
    metrics = _read_metrics(root / "metrics", source_errors)
    events, event_facts = _read_events(
        root / "trajectory.jsonl",
        max_events=max_events,
        max_text_chars=max_text_chars,
        source_errors=source_errors,
    )
    task = _failing_task(state)
    verifier = _verifier_evidence(
        state,
        metrics,
        event_facts["verifier_details"],
        max_text_chars,
        task,
    )
    model_errors = _model_errors(
        metrics,
        event_facts["model_errors"],
        max_text_chars,
        max_events,
    )
    checkpoint = _checkpoint_state(
        metrics,
        event_facts,
        task,
    )
    failure_class = _failure_class(
        state,
        task,
        verifier,
        model_errors,
        metrics,
        checkpoint,
        event_facts,
    )
    artifacts = _artifacts(root, max_artifacts)

    run_id = str(state.get("run_id") or root.name)
    return {
        "run_id": run_id,
        "status": str(state.get("status") or "unknown"),
        "failure_class": failure_class,
        "failing_task": task,
        "events": events,
        "verifier": verifier,
        "model_errors": model_errors,
        "checkpoint": checkpoint,
        "artifacts": artifacts["names"],
        "artifacts_omitted": artifacts["omitted"],
        "summary": _summary(run_id, failure_class, task, verifier),
        "source_errors": source_errors[:max_events],
    }


def _read_object(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"missing artifact: {path.name}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"could not read {path.name}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"invalid object: {path.name}")
        return {}
    return value


def _read_metrics(metrics_dir: Path, errors: list[str]) -> list[dict[str, Any]]:
    if not metrics_dir.is_dir():
        return []
    metrics: list[dict[str, Any]] = []
    for path in sorted(metrics_dir.glob("*.json")):
        value = _read_object(path, errors)
        if value:
            metrics.append(value)
    return metrics


def _read_events(
    path: Path,
    *,
    max_events: int,
    max_text_chars: int,
    source_errors: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    recent: deque[dict[str, Any]] = deque(maxlen=max_events)
    verifier_details: deque[str] = deque(maxlen=max_events)
    model_errors: list[dict[str, Any]] = []
    checkpoint_failed = False
    checkpoint_created = False
    rollback_observed = False
    commit: str | None = None
    if not path.is_file():
        return [], {
            "verifier_details": list(verifier_details),
            "model_errors": model_errors,
            "checkpoint_failed": checkpoint_failed,
            "checkpoint_created": checkpoint_created,
            "rollback_observed": rollback_observed,
            "commit": commit,
        }

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        source_errors.append(f"could not read trajectory.jsonl: {exc}")
        return [], {
            "verifier_details": list(verifier_details),
            "model_errors": model_errors,
            "checkpoint_failed": checkpoint_failed,
            "checkpoint_created": checkpoint_created,
            "rollback_observed": rollback_observed,
            "commit": commit,
        }

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if len(source_errors) < max_events:
                source_errors.append(f"invalid trajectory line {line_number}: {exc}")
            continue
        if not isinstance(event, dict):
            continue

        event_name = str(event.get("event") or "unknown")
        detail = event.get("detail")
        if isinstance(detail, str):
            if "verification" in event_name or event_name in {"task_completed", "tests_finished"}:
                if max_events:
                    verifier_details.append(detail)
        if _is_model_error(event_name, event) and len(model_errors) < max_events:
            model_errors.append(_compact_model_error(event, max_text_chars))

        if event_name == "checkpoint_failed":
            checkpoint_failed = True
        elif event_name == "checkpoint_created":
            checkpoint_created = True
            commit = _commit_from_detail(detail) or commit
        elif event_name == "rollback":
            rollback_observed = True

        compact = _compact_event(event, line_number, max_text_chars)
        if max_events:
            recent.append(compact)

    return list(recent), {
        "verifier_details": list(verifier_details),
        "model_errors": model_errors,
        "checkpoint_failed": checkpoint_failed,
        "checkpoint_created": checkpoint_created,
        "rollback_observed": rollback_observed,
        "commit": commit,
    }


def _compact_event(
    event: dict[str, Any],
    line_number: int,
    max_text_chars: int,
) -> dict[str, Any]:
    compact: dict[str, Any] = {"id": line_number}
    for key in (
        "timestamp",
        "run_id",
        "task_id",
        "event",
        "model",
        "attempt",
        "passed",
        "failure_class",
        "verification_phase",
        "verification_classification",
        "failure_identities",
    ):
        if key in event and event[key] is not None:
            compact[key] = event[key]
    if isinstance(event.get("detail"), str):
        compact["detail"] = _clip(event["detail"], max_text_chars)
    return compact


def _compact_model_error(event: dict[str, Any], max_text_chars: int) -> dict[str, Any]:
    error: dict[str, Any] = {"event": event.get("event")}
    for key in ("task_id", "model", "attempt", "failure_class"):
        if event.get(key) is not None:
            error[key] = event[key]
    if isinstance(event.get("detail"), str):
        error["detail"] = _clip(event["detail"], max_text_chars)
    return error


def _is_model_error(event_name: str, event: dict[str, Any]) -> bool:
    return bool(
        event.get("failure_class")
        or event_name in {"task_exception", "model_error", "backend_error"}
        or event_name == "model_attempt_failed"
        or event_name == "coding_output_rejected"
    ) and "verification" not in event_name


def _read_streams(text: str) -> tuple[str, str, int | None]:
    returncode: int | None = None
    match = re.search(r"(?:^|\n)returncode=(-?\d+)", text)
    if match:
        returncode = int(match.group(1))
    stdout = ""
    stderr = ""
    if "STDOUT:" in text:
        remainder = text.split("STDOUT:", 1)[1]
        stderr_match = re.search(r"\n+STDERR:", remainder)
        if stderr_match:
            stdout = remainder[:stderr_match.start()]
            stderr = remainder[stderr_match.end():]
        else:
            stdout = remainder
    elif "STDERR:" in text:
        stderr = text.split("STDERR:", 1)[1]
    return stdout.strip(), stderr.strip(), returncode


def _verifier_evidence(
    state: dict[str, Any],
    metrics: list[dict[str, Any]],
    event_details: list[str],
    max_text_chars: int,
    task: dict[str, str] | None,
) -> dict[str, Any]:
    stdout = ""
    stderr = ""
    raw_detail = ""
    returncode: int | None = None
    task_values = state.get("tasks", [])
    if isinstance(task_values, list):
        for task in task_values:
            if isinstance(task, dict) and isinstance(task.get("error"), str):
                raw_detail = task["error"]
                task_stdout, task_stderr, task_returncode = _read_streams(task["error"])
                stdout, stderr = task_stdout or stdout, task_stderr or stderr
                if task_returncode is not None:
                    returncode = task_returncode
    for detail in event_details:
        raw_detail = detail
        event_stdout, event_stderr, event_returncode = _read_streams(detail)
        stdout, stderr = event_stdout or stdout, event_stderr or stderr
        returncode = event_returncode if event_returncode is not None else returncode
    metric = {}
    if task:
        metric = next(
            (
                candidate
                for candidate in reversed(metrics)
                if candidate.get("task_id") == task.get("id")
            ),
            {},
        )
    elif metrics:
        metric = metrics[-1]
    if isinstance(metric.get("test_returncode"), int):
        returncode = metric["test_returncode"]
    if not stdout and not stderr and raw_detail:
        stderr = raw_detail
    return {
        "returncode": returncode,
        "stdout": _clip(stdout, max_text_chars),
        "stderr": _clip(stderr, max_text_chars),
        "classification": metric.get("verification_classification"),
        "baseline_returncode": metric.get("baseline_returncode"),
        "baseline_passed": metric.get("baseline_passed"),
    }


def _model_errors(
    metrics: list[dict[str, Any]],
    event_errors: list[dict[str, Any]],
    max_text_chars: int,
    max_events: int,
) -> list[dict[str, Any]]:
    errors = list(event_errors)
    for metric in metrics:
        for failure in metric.get("operation_failures", []):
            if not isinstance(failure, dict):
                continue
            item = {"event": "operation_failure"}
            if metric.get("task_id") is not None:
                item["task_id"] = metric["task_id"]
            for key in ("model", "attempt", "failure_class"):
                if failure.get(key) is not None:
                    item[key] = failure[key]
            if isinstance(failure.get("detail"), str):
                item["detail"] = _clip(failure["detail"], max_text_chars)
            errors.append(item)
    return errors[:max_events]


def _checkpoint_state(
    metrics: list[dict[str, Any]],
    facts: dict[str, Any],
    task: dict[str, Any] | None,
) -> dict[str, Any]:
    commit = facts["commit"]
    for metric in metrics:
        if isinstance(metric.get("commit"), str):
            commit = metric["commit"]
    failed = facts["checkpoint_failed"] or (
        isinstance(task, dict)
        and "checkpoint" in str(task.get("error", "")).lower()
    )
    return {
        "commit": commit,
        "created": bool(facts["checkpoint_created"] or commit),
        "failed": failed,
        "rollback_observed": bool(facts["rollback_observed"]),
    }


def _failure_class(
    state: dict[str, Any],
    task: dict[str, Any] | None,
    verifier: dict[str, Any],
    model_errors: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    facts: dict[str, Any],
) -> str:
    status = str(state.get("status") or "unknown")
    if status in {"pending", "running", "waiting_for_approval"}:
        return "in_progress"
    if status == "passed":
        return "none"
    if checkpoint["failed"]:
        return "checkpoint_failure"
    if _task_verification_failed(state, task):
        return "verification_failure"
    current_task_id = task.get("id") if task else None
    current_metrics = (
        [metric for metric in metrics if metric.get("task_id") == current_task_id]
        if current_task_id
        else metrics
    )
    current_model_errors = (
        [
            error
            for error in model_errors
            if not error.get("task_id") or error.get("task_id") == current_task_id
        ]
        if current_task_id
        else model_errors
    )
    if any(metric.get("operation_failures") for metric in current_metrics):
        return "operation_failure"
    if current_model_errors:
        return "model_or_backend_error"
    if verifier["returncode"] not in {None, 0} or verifier["classification"]:
        return "verification_failure"
    if task and task.get("status") in {"blocked", "skipped"}:
        return "dependency_blocked"
    if task and task.get("status") == "failed":
        return "task_failure"
    return "unknown_failure"


def _task_verification_failed(
    state: dict[str, Any],
    task: dict[str, str] | None,
) -> bool:
    if not task:
        return False
    for value in state.get("tasks", []):
        if isinstance(value, dict) and value.get("id") == task.get("id"):
            return value.get("verification_status") == "failed"
    return False


def _failing_task(state: dict[str, Any]) -> dict[str, str] | None:
    tasks = state.get("tasks", [])
    if not isinstance(tasks, list):
        return None
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") != "failed":
            continue
        return {
            "id": str(task.get("id", "unknown")),
            "description": str(task.get("description", "")),
            "status": "failed",
        }
    return None


def _artifacts(root: Path, max_artifacts: int) -> dict[str, Any]:
    names = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )
    return {
        "names": names[:max_artifacts],
        "omitted": max(0, len(names) - max_artifacts),
    }


def _commit_from_detail(detail: Any) -> str | None:
    if not isinstance(detail, str):
        return None
    match = re.search(r"commit=([0-9a-f]{7,64})", detail)
    return match.group(1) if match else None


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def _summary(
    run_id: str,
    failure_class: str,
    task: dict[str, Any] | None,
    verifier: dict[str, Any],
) -> str:
    if failure_class == "none":
        return f"Run {run_id} passed."
    if failure_class == "in_progress":
        return f"Run {run_id} is still in progress."
    suffix = f" at task {task['id']}" if task else ""
    summary = f"Run {run_id} failed ({failure_class}){suffix}."
    classification = verifier.get("classification")
    if isinstance(classification, str) and classification:
        summary += f" Verification: {classification}."
    text = str(verifier.get("stderr") or verifier.get("stdout") or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    evidence = next(
        (
            line
            for line in lines
            if "Error" in line or "ERROR" in line or "FAILED" in line
        ),
        lines[0] if lines else "",
    )
    if evidence:
        summary += f" {evidence[:240]}"
    return summary
