from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from local_agent_orchestrator.models.task import (
    RunState,
    TaskState,
    TaskStatus,
    VerificationStatus,
)
from local_agent_orchestrator.models.trajectory import TrajectoryEvent
from local_agent_orchestrator.services.trajectory import append_trajectory_event


class RunStateManager:
    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)

    def create_run(self, request: str) -> RunState:
        run_id = uuid4().hex[:12]
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        state = RunState(
            run_id=run_id,
            request=request,
        )

        (run_dir / "request.md").write_text(
            request.strip() + "\n",
            encoding="utf-8",
        )

        self.save(state)
        return state

    def get_run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def save(self, state: RunState) -> None:
        state.updated_at = datetime.now(timezone.utc)

        path = self.get_run_dir(state.run_id) / "state.json"

        path.write_text(
            json.dumps(
                state.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def load(self, run_id: str) -> RunState:
        path = self.get_run_dir(run_id) / "state.json"

        if not path.exists():
            raise FileNotFoundError(
                f"Run not found: {run_id}"
            )

        return RunState.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def add_task(
        self,
        state: RunState,
        description: str,
        verification: list[str] | None = None,
    ) -> TaskState:
        task = TaskState(
            id=f"task-{len(state.tasks) + 1:03d}",
            description=description,
            verification=list(verification or []),
            verification_status=(
                VerificationStatus.INFORMATIONAL
                if verification
                else VerificationStatus.NOT_REQUESTED
            ),
        )

        state.tasks.append(task)
        self.save(state)

        return task

    def get_task(
        self,
        state: RunState,
        task_id: str,
    ) -> TaskState:
        for task in state.tasks:
            if task.id == task_id:
                return task

        raise KeyError(
            f"Task not found: {task_id}"
        )

    def mark_waiting_for_approval(
        self,
        state: RunState,
        task_id: str,
    ) -> None:
        task = self.get_task(
            state,
            task_id,
        )

        task.status = TaskStatus.WAITING_FOR_APPROVAL
        task.error = None

        state.status = TaskStatus.WAITING_FOR_APPROVAL
        state.current_task = task_id

        self.save(state)
        append_trajectory_event(
            self.get_run_dir(state.run_id),
            TrajectoryEvent(
                run_id=state.run_id,
                task_id=task_id,
                event="approval_requested",
                passed=False,
                detail="Human approval is required before execution.",
            ),
        )

    def approve_task(
        self,
        state: RunState,
        task_id: str,
    ) -> None:
        task = self.get_task(
            state,
            task_id,
        )

        if task.status != TaskStatus.WAITING_FOR_APPROVAL:
            raise RuntimeError(
                f"Task {task_id} is not waiting for approval."
            )

        task.approval_granted = True
        task.status = TaskStatus.PENDING
        task.error = None

        state.status = TaskStatus.PENDING
        state.current_task = task_id

        self.save(state)
        append_trajectory_event(
            self.get_run_dir(state.run_id),
            TrajectoryEvent(
                run_id=state.run_id,
                task_id=task_id,
                event="approval_granted",
                passed=True,
                detail="Human approval granted.",
            ),
        )

    def mark_blocked(
        self,
        state: RunState,
        task_id: str,
        reason: str,
    ) -> None:
        task = self.get_task(state, task_id)
        task.status = TaskStatus.BLOCKED
        task.error = reason
        state.status = TaskStatus.FAILED
        state.current_task = task_id
        self.save(state)

    def mark_skipped(
        self,
        state: RunState,
        task_id: str,
        reason: str,
    ) -> None:
        task = self.get_task(state, task_id)
        task.status = TaskStatus.SKIPPED
        task.error = reason
        state.status = TaskStatus.FAILED
        state.current_task = task_id
        self.save(state)

    def set_verification_status(
        self,
        state: RunState,
        task_id: str,
        status: VerificationStatus,
    ) -> None:
        task = self.get_task(state, task_id)
        task.verification_status = status
        self.save(state)

    def finish_run(self, state: RunState, passed: bool) -> None:
        state.status = TaskStatus.PASSED if passed else TaskStatus.FAILED
        state.current_task = None
        self.save(state)

    def update_task(
        self,
        state: RunState,
        task_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        task = self.get_task(
            state,
            task_id,
        )

        task.status = status
        task.error = error

        if status == TaskStatus.RUNNING:
            task.attempts += 1

        state.current_task = task_id

        if status == TaskStatus.FAILED:
            state.status = TaskStatus.FAILED

        elif status in {TaskStatus.BLOCKED, TaskStatus.SKIPPED}:
            state.status = TaskStatus.FAILED

        elif status == TaskStatus.WAITING_FOR_APPROVAL:
            state.status = TaskStatus.WAITING_FOR_APPROVAL

        elif all(
            item.status == TaskStatus.PASSED
            for item in state.tasks
        ):
            state.status = TaskStatus.PASSED
            state.current_task = None

        else:
            state.status = TaskStatus.RUNNING

        self.save(state)
