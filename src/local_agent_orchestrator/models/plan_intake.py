from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from local_agent_orchestrator.models.plan import (
    ExecutionPlan,
    TaskKind,
    TaskRisk,
)
from local_agent_orchestrator.models.project_spec import ProjectIntent, ProjectSpec


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
    primary_scope: list[str] = Field(default_factory=list)
    discouraged_scope: list[str] = Field(default_factory=list)
    forbidden_scope: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    risk: TaskRisk = "low"

    @model_validator(mode="before")
    @classmethod
    def migrate_file_boundaries(cls, value):
        if isinstance(value, dict) and "file_boundaries" in value:
            value = dict(value)
            value.setdefault("primary_scope", value.pop("file_boundaries"))
        return value

    @property
    def file_boundaries(self) -> list[str]:
        return self.primary_scope


class PlanCandidateProject(BaseModel):
    """High-level project intent emitted by the planner/compiler model."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    slug: str | None = Field(default=None, min_length=1)
    intent: ProjectIntent = "new"
    language: str | None = None
    framework: str | None = None
    engine: str | None = None
    project_type: str | None = None
    database: str | None = None
    runtime: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    research_questions: list[str] = Field(default_factory=list)
    edit_boundaries: list[str] = Field(default_factory=list)
    review_requirements: list[str] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)


class PlanCandidate(BaseModel):
    """The only shape accepted from the Bonsai compiler."""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1)
    project: PlanCandidateProject | None = None
    tasks: list[PlanCandidateTask] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


CompileStatus = Literal["compiled", "rejected", "failed"]


class PlanIntakeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CompileStatus
    plan: ExecutionPlan | None = None
    project_spec: ProjectSpec | None = None
    assumptions: list[str] = Field(default_factory=list)
    unresolved_issues: list[str] = Field(default_factory=list)
    error: str | None = None
    compiled_revision: int | None = Field(default=None, ge=1)
    compiled_digest: str | None = None
    source_digest: str | None = None
    compiled_at: str | None = None
