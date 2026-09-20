from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ToolName = Literal[
    "list_files",
    "search_text",
    "read_file",
    "git_status",
    "git_diff",
]


class ToolAction(BaseModel):
    tool: ToolName
    path: str | None = None
    query: str | None = None
    max_results: int = Field(default=50, ge=1, le=200)


class ToolObservation(BaseModel):
    tool: ToolName
    ok: bool
    content: str
