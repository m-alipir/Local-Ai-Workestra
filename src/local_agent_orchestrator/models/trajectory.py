from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class TrajectoryEvent(BaseModel):
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    run_id: str
    task_id: str
    event: str
    model: str | None = None
    attempt: int | None = None
    passed: bool | None = None
    detail: str | None = None
    operations: list[dict] | None = None
    failure_class: str | None = None
    verification_phase: str | None = None
    failure_identities: list[str] | None = None
    verification_classification: str | None = None
    scope_decision: str | None = None
    scope_paths: list[str] | None = None
