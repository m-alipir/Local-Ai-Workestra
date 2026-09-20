from __future__ import annotations

from pathlib import Path

from local_agent_orchestrator.models.plan import ExecutionPlan


def load_plan(path: str | Path) -> ExecutionPlan:
    plan_path = Path(path)

    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")

    return ExecutionPlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
