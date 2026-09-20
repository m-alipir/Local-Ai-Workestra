from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from local_agent_orchestrator.models.plan import ExecutionPlan
from local_agent_orchestrator.services.plan_runner import (
    PlanRunResult,
    run_execution_plan,
)
from local_agent_orchestrator.services.sol_planner import (
    build_plan_with_codex,
)


@dataclass(slots=True)
class PlannerPipelineResult:
    plan: ExecutionPlan
    plan_path: Path
    run: PlanRunResult


def run_planned_request(
    request: str,
    workspace_root: str | Path,
    test_command: list[str],
    plans_dir: str | Path = ".agent/plans",
    runs_dir: str | Path = "runs",
    analytics_dir: str | Path = ".agent/analytics",
    planner_model: str = "gpt-5.6-sol",
) -> PlannerPipelineResult:
    plan = build_plan_with_codex(
        request=request,
        workspace_root=workspace_root,
        model=planner_model,
    )

    plans_root = Path(plans_dir)
    plans_root.mkdir(parents=True, exist_ok=True)

    plan_path = plans_root / "latest-plan.json"

    plan_path.write_text(
        json.dumps(
            plan.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    run = run_execution_plan(
        plan=plan,
        workspace_root=workspace_root,
        test_command=test_command,
        runs_dir=runs_dir,
        analytics_dir=analytics_dir,
    )

    return PlannerPipelineResult(
        plan=plan,
        plan_path=plan_path,
        run=run,
    )
