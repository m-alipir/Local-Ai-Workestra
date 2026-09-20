from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TaskKind = Literal[
    "code",
    "test",
    "review",
    "docs",
    "deploy",
    "manual",
]

TaskRisk = Literal[
    "low",
    "medium",
    "high",
    "critical",
]


class PlanTask(BaseModel):
    id: str | None = None
    description: str = Field(min_length=1)

    kind: TaskKind = "code"
    depends_on: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)

    requires_approval: bool = False
    risk: TaskRisk = "low"


class ExecutionPlan(BaseModel):
    request: str = Field(min_length=1)
    tasks: list[PlanTask] = Field(min_length=1)
