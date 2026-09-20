from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from local_agent_orchestrator.models.security import SecurityReview


class TaskMetrics(BaseModel):
    task_id: str
    description: str
    started_at: datetime
    finished_at: datetime
    duration_sec: float = Field(ge=0)
    attempts: int = Field(ge=0)
    passed: bool
    changed_files: list[str]
    test_returncode: int
    commit: str | None = None
    diagnoses: list[str] = Field(default_factory=list)
    qwen_attempts: int = Field(default=0, ge=0)
    devstral_used: bool = False
    accepted_model: str | None = None
    accepted_attempt: int | None = None
    operation_failures: list[dict[str, str | int]] = Field(
        default_factory=list,
    )
    diagnosis_count: int = Field(default=0, ge=0)
    security_review_used: bool = False
    optimization_review_used: bool = False
    model_reasoning: dict[str, str] = Field(default_factory=dict)
    security_review: SecurityReview | None = None
    optimization_review: str | None = None
    baseline_returncode: int | None = None
    baseline_passed: bool | None = None
    baseline_failure_identities: list[str] = Field(default_factory=list)
    post_change_failure_identities: list[str] = Field(default_factory=list)
    verification_classification: str | None = None
