from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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

    @field_validator("primary_scope", "discouraged_scope", "forbidden_scope")
    @classmethod
    def validate_scope_paths(cls, value: list[str]) -> list[str]:
        for boundary in value:
            normalized = boundary.replace("\\", "/")
            if normalized.endswith("/"):
                normalized = normalized.rstrip("/")
            if (
                not normalized
                or normalized.startswith("/")
                or re.match(r"^[A-Za-z]:/", normalized)
                or any(part in {"", ".", ".."} for part in normalized.split("/"))
            ):
                raise ValueError("scope paths must contain safe relative paths")
        return value

    @property
    def file_boundaries(self) -> list[str]:
        """Compatibility view for plans created before the scope model."""
        return self.primary_scope


class ExecutionPlan(BaseModel):
    request: str = Field(min_length=1)
    tasks: list[PlanTask] = Field(min_length=1)
