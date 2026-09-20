from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["low", "medium", "high", "critical"]


class SecurityFinding(BaseModel):
    severity: Severity
    title: str
    description: str
    recommendation: str


class SecurityReview(BaseModel):
    findings: list[SecurityFinding] = Field(default_factory=list)

    @property
    def has_blocking_findings(self) -> bool:
        return any(
            finding.severity in ("high", "critical")
            for finding in self.findings
        )
