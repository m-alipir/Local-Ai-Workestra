from pathlib import Path
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.models.plan import (
    ExecutionPlan,
    PlanTask,
)
from local_agent_orchestrator.services.planner_pipeline import (
    run_planned_request,
)


def test_run_planned_request(tmp_path):
    plan = ExecutionPlan(
        request="Build calculator",
        tasks=[
            PlanTask(
                description="Create calculator module"
            ),
            PlanTask(
                description="Add subtraction support"
            ),
        ],
    )

    fake_run = MagicMock(
        run_id="run123",
        passed=True,
        completed_tasks=2,
        total_tasks=2,
        commits=["a", "b"],
        run_dir=Path("runs/run123"),
        analytics_path=Path("analytics.json"),
        retrospective_path=Path("retrospective.md"),
    )

    with (
        patch(
            "local_agent_orchestrator.services.planner_pipeline.build_plan_with_codex",
            return_value=plan,
        ) as planner,
        patch(
            "local_agent_orchestrator.services.planner_pipeline.run_execution_plan",
            return_value=fake_run,
        ) as runner,
    ):
        result = run_planned_request(
            request="Build calculator",
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            plans_dir=tmp_path / "plans",
            runs_dir=tmp_path / "runs",
            analytics_dir=tmp_path / "analytics",
        )

    assert result.plan_path.exists()
    assert result.plan.tasks[0].description == "Create calculator module"
    assert result.run.passed is True
    planner.assert_called_once()
    runner.assert_called_once()
