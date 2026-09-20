from __future__ import annotations

import json

from pydantic import ValidationError

from local_agent_orchestrator.models.patch import PatchSet
from local_agent_orchestrator.services.workspace import Workspace


class PatchError(RuntimeError):
    pass


def parse_patch_response(text: str) -> PatchSet:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    json_start = cleaned.find("{")

    if json_start == -1:
        raise PatchError("Model response contains no JSON object.")

    cleaned = cleaned[json_start:]

    decoder = json.JSONDecoder()

    try:
        data, _ = decoder.raw_decode(cleaned)
    except json.JSONDecodeError as exc:
        raise PatchError(
            f"Model returned invalid JSON: {exc}"
        ) from exc

    try:
        return PatchSet.model_validate(data)
    except ValidationError as exc:
        raise PatchError(
            f"Model returned invalid patch schema: {exc}"
        ) from exc


def apply_patch_set(
    workspace: Workspace,
    patch_set: PatchSet,
) -> list[str]:
    changed: list[str] = []

    for patch in patch_set.files:
        workspace.write_text(
            patch.path,
            patch.content,
        )
        changed.append(patch.path)

    return changed


from pydantic import BaseModel, ConfigDict, Field


class DiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: str = Field(min_length=1)


def parse_diff_response(text: str) -> str:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    json_start = cleaned.find("{")

    if json_start == -1:
        raise PatchError(
            "Model response contains no JSON object."
        )

    decoder = json.JSONDecoder()

    try:
        data, _ = decoder.raw_decode(
            cleaned[json_start:]
        )
    except json.JSONDecodeError as exc:
        raise PatchError(
            f"Model returned invalid JSON: {exc}"
        ) from exc

    try:
        response = DiffResponse.model_validate(data)
    except ValidationError as exc:
        raise PatchError(
            f"Model returned invalid diff schema: {exc}"
        ) from exc

    patch = response.patch.strip()

    if not patch.startswith("diff --git "):
        raise PatchError(
            "Model patch is not a git unified diff."
        )

    return patch + "\n"
