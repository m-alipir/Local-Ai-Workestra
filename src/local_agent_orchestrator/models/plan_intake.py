from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from local_agent_orchestrator.models.plan import (
    ExecutionPlan,
    TaskKind,
    TaskRisk,
)


class PlanIntake(BaseModel):
    """Untrusted Markdown preserved at the intake boundary."""

    model_config = ConfigDict(extra="forbid")

    markdown: str = Field(min_length=1)
    stored_path: str | None = None


class PlanCandidateTask(BaseModel):
    """Strict model output accepted before conversion to Plan v2."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1)
    description: str = Field(min_length=1)
    kind: TaskKind = "code"
    depends_on: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    risk: TaskRisk = "low"


class PlanCandidate(BaseModel):
    """The only shape accepted from the Bonsai compiler."""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1)
    tasks: list[PlanCandidateTask] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


CompileStatus = Literal["compiled", "rejected", "failed"]


class PlanIntakeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CompileStatus
    plan: ExecutionPlan | None = None
    assumptions: list[str] = Field(default_factory=list)
    unresolved_issues: list[str] = Field(default_factory=list)
    error: str | None = None

