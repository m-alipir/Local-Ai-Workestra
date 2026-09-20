from __future__ import annotations

from dataclasses import dataclass

from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask


class PlanValidationError(ValueError):
    """A plan cannot be executed safely as written."""


_SUPPORTED_KINDS = {
    "code",
    "test",
    "review",
    "docs",
    "deploy",
    "manual",
}
_SUPPORTED_RISKS = {"low", "medium", "high", "critical"}


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    effective_ids: tuple[str, ...]
    order: tuple[int, ...]


def _effective_task_id(task: PlanTask, generated_id: str) -> str:
    return task.id or generated_id


def validate_plan(
    plan: ExecutionPlan,
    generated_ids: list[str] | None = None,
) -> ValidatedPlan:
    if generated_ids is None:
        generated_ids = [
            f"task-{index:03d}"
            for index, _ in enumerate(plan.tasks, start=1)
        ]

    if len(generated_ids) != len(plan.tasks):
        raise PlanValidationError(
            "Generated task IDs do not match the plan task count."
        )

    effective_ids = tuple(
        _effective_task_id(task, generated_id)
        for task, generated_id in zip(
            plan.tasks,
            generated_ids,
            strict=True,
        )
    )

    if any(not task_id for task_id in effective_ids):
        raise PlanValidationError("Plan task IDs cannot be empty.")

    if len(effective_ids) != len(set(effective_ids)):
        raise PlanValidationError("Plan contains duplicate task IDs.")

    known_ids = set(effective_ids)
    indices = {task_id: index for index, task_id in enumerate(effective_ids)}
    dependents: dict[str, list[int]] = {
        task_id: [] for task_id in effective_ids
    }
    indegree: list[int] = []

    for index, (task, effective_id) in enumerate(
        zip(plan.tasks, effective_ids, strict=True)
    ):
        if task.kind not in _SUPPORTED_KINDS:
            raise PlanValidationError(
                f"Task {effective_id} has unsupported kind {task.kind!r}."
            )
        if task.risk not in _SUPPORTED_RISKS:
            raise PlanValidationError(
                f"Task {effective_id} has unsupported risk {task.risk!r}."
            )
        dependencies = list(task.depends_on)
        for dependency in dependencies:
            if dependency not in known_ids:
                raise PlanValidationError(
                    f"{effective_id} depends on unknown task {dependency}."
                )
            if dependency == effective_id:
                raise PlanValidationError(
                    f"{effective_id} cannot depend on itself."
                )
            dependents[dependency].append(index)
        indegree.append(len(dependencies))

    ready = [index for index, degree in enumerate(indegree) if degree == 0]
    order: list[int] = []

    while ready:
        index = ready.pop(0)
        order.append(index)

        for dependent in sorted(
            dependents[effective_ids[index]],
            key=lambda item: indices[effective_ids[item]],
        ):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(order) != len(plan.tasks):
        remaining = [
            effective_ids[index]
            for index, degree in enumerate(indegree)
            if degree > 0
        ]
        raise PlanValidationError(
            "Plan dependency cycle detected: "
            + ", ".join(remaining)
        )

    return ValidatedPlan(
        effective_ids=effective_ids,
        order=tuple(order),
    )
