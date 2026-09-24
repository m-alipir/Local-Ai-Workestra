from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ScopeDecision = Literal["PASS", "REVISE", "RETRY_FRESH", "FAIL_HARD"]


SCOPE_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "task_scope_review",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["PASS", "REVISE", "RETRY_FRESH", "FAIL_HARD"],
                },
                "reason": {"type": "string"},
                "preserve_paths": {"type": "array", "items": {"type": "string"}},
                "remove_paths": {"type": "array", "items": {"type": "string"}},
                "instruction": {"type": "string"},
            },
            "required": [
                "decision",
                "reason",
                "preserve_paths",
                "remove_paths",
                "instruction",
            ],
            "additionalProperties": False,
        },
    },
}


class ScopeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ScopeDecision
    reason: str = Field(min_length=1)
    preserve_paths: list[str] = Field(default_factory=list)
    remove_paths: list[str] = Field(default_factory=list)
    instruction: str = ""
