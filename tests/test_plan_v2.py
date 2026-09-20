from local_agent_orchestrator.models.plan import (
    ExecutionPlan,
    PlanTask,
)


def test_plan_task_v2_defaults_preserve_old_plans():
    task = PlanTask(
        description="Implement feature"
    )

    assert task.kind == "code"
    assert task.risk == "low"
    assert task.requires_approval is False
    assert task.depends_on == []
    assert task.verification == []


def test_plan_task_v2_supports_execution_metadata():
    plan = ExecutionPlan(
        request="Deploy validated release",
        tasks=[
            PlanTask(
                id="task-001",
                description="Run production deployment",
                kind="deploy",
                depends_on=["task-000"],
                verification=[
                    "app is healthy",
                    "migration exited 0",
                ],
                requires_approval=True,
                risk="high",
            )
        ],
    )

    task = plan.tasks[0]

    assert task.id == "task-001"
    assert task.kind == "deploy"
    assert task.depends_on == ["task-000"]
    assert task.requires_approval is True
    assert task.risk == "high"
    assert len(task.verification) == 2
