from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ProjectIntent = Literal["new", "existing"]
CapabilityName = Literal[
    "python",
    "fastapi",
    "sqlite",
    "sqlalchemy",
    "pytest",
    "api-testing",
    "node",
    "typescript",
    "react",
    "vite",
    "godot",
    "gdscript",
]


class ResearchRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    blocking: bool = True


class ProjectSpec(BaseModel):
    """Trusted, run-facing project definition produced by the compiler."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    intent: ProjectIntent = "new"
    workspace_root: str | None = None
    language: str | None = None
    framework: str | None = None
    engine: str | None = None
    project_type: str | None = None
    database: str | None = None
    runtime: str | None = None
    capabilities: list[CapabilityName] = Field(default_factory=list)
    bootstrap_profile: str | None = None
    verifier: list[str] | None = None
    edit_boundaries: list[str] = Field(default_factory=list)
    review_requirements: list[str] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    research_requirements: list[ResearchRequirement] = Field(default_factory=list)

    @field_validator("workspace_root")
    @classmethod
    def validate_workspace_root(cls, value: str | None) -> str | None:
        if value is not None:
            path = Path(value)
            if not value or ".." in path.parts or (not path.is_absolute() and any(part in {"", "."} for part in value.split("/"))):
                raise ValueError("workspace_root must be a safe project path")
        return value

    @field_validator("verifier")
    @classmethod
    def validate_verifier(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and value not in [["uv", "run", "pytest", "-q"]]:
            raise ValueError("verifier must use Workestra's trusted verifier profile")
        return value
