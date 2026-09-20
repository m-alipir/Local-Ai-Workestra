from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class VerificationStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    INFORMATIONAL = "informational"
    ENFORCED_TRUSTED_COMMAND = "enforced_trusted_command"
    FAILED = "failed"


class TaskState(BaseModel):
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    error: str | None = None
    approval_granted: bool = False
    verification: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.NOT_REQUESTED


class RunState(BaseModel):
    run_id: str
    request: str
    status: TaskStatus = TaskStatus.PENDING
    current_task: str | None = None
    base_branch: str | None = None
    agent_branch: str | None = None
    tasks: list[TaskState] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
