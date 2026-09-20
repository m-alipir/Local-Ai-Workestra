from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EDIT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "edit_operations_response",
        "schema": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["replace_exact"],
                                    },
                                    "path": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "old_text": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "new_text": {"type": "string"},
                                },
                                "required": [
                                    "kind",
                                    "path",
                                    "old_text",
                                    "new_text",
                                ],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["create_file"],
                                    },
                                    "path": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "content": {"type": "string"},
                                },
                                "required": ["kind", "path", "content"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["delete_file"],
                                    },
                                    "path": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                },
                                "required": ["kind", "path"],
                                "additionalProperties": False,
                            },
                        ],
                    },
                },
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    },
}


class EditOperation(BaseModel):
    """One semantic edit requested by a coding model."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["replace_exact", "create_file", "delete_file"]
    path: str = Field(min_length=1)
    old_text: str | None = None
    new_text: str | None = None
    content: str | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> EditOperation:
        if self.kind == "replace_exact":
            if self.old_text is None or not self.old_text:
                raise ValueError(
                    "replace_exact requires a non-empty old_text"
                )
            if self.new_text is None:
                raise ValueError(
                    "replace_exact requires new_text"
                )
            if self.content is not None:
                raise ValueError(
                    "replace_exact does not accept content"
                )
        elif self.kind == "create_file":
            if self.content is None:
                raise ValueError(
                    "create_file requires content"
                )
            if self.old_text is not None or self.new_text is not None:
                raise ValueError(
                    "create_file does not accept replacement fields"
                )
        else:
            if (
                self.old_text is not None
                or self.new_text is not None
                or self.content is not None
            ):
                raise ValueError(
                    "delete_file does not accept content fields"
                )

        return self


class EditOperationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[EditOperation] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_unique_paths(self) -> EditOperationsResponse:
        paths = [operation.path for operation in self.operations]
        if len(paths) != len(set(paths)):
            raise ValueError(
                "operations must not contain duplicate paths"
            )
        return self
