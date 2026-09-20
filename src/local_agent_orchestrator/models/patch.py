from __future__ import annotations

from pydantic import BaseModel, Field


class FilePatch(BaseModel):
    path: str = Field(min_length=1)
    content: str


class PatchSet(BaseModel):
    files: list[FilePatch] = Field(min_length=1)
