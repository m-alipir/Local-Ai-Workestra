from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from local_agent_orchestrator.models.plan import ExecutionPlan
from local_agent_orchestrator.services.plan_validation import (
    PlanValidationError,
    validate_plan,
)


class SolPlannerError(RuntimeError):
    pass


def build_plan_with_codex(
    request: str,
    workspace_root: str | Path,
    model: str = "gpt-5.6-sol",
) -> ExecutionPlan:
    workspace = Path(workspace_root).resolve()

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["request", "tasks"],
        "properties": {
            "request": {
                "type": "string"
            },
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["description"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "description": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "kind": {
                            "type": "string",
                            "enum": [
                                "code",
                                "test",
                                "review",
                                "docs",
                                "deploy",
                                "manual",
                            ],
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "verification": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "requires_approval": {
                            "type": "boolean",
                        },
                        "risk": {
                            "type": "string",
                            "enum": [
                                "low",
                                "medium",
                                "high",
                                "critical",
                            ],
                        }
                    }
                }
            }
        }
    }

    prompt = f"""You are the planning architect for a local coding-agent system.

Analyze the repository and the user request.

USER REQUEST:
{request}

Produce a minimal implementation plan.

Rules:
- Break the work into small sequential coding tasks.
- Each task must be independently testable when practical.
- Preserve existing architecture unless change is required.
- Do not implement anything.
- Do not modify files.
- Do not include speculative infrastructure.
- Put prerequisite tasks before dependent tasks.
- Use only these task kinds: code, test, review, docs, deploy, manual.
- Use depends_on with task IDs only when a prerequisite is required.
- risk=high or critical requires human approval even if requires_approval is omitted.
- verification entries are descriptive metadata; never put shell commands there.
- Return only the requested structured output.
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        schema_path = Path(temp_dir) / "plan-schema.json"
        output_path = Path(temp_dir) / "plan-output.json"

        schema_path.write_text(
            json.dumps(schema, indent=2),
            encoding="utf-8",
        )

        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--model",
            model,
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-C",
            str(workspace),
            prompt,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise SolPlannerError(
                result.stderr.strip()
                or result.stdout.strip()
                or "Codex planner failed."
            )

        if not output_path.exists():
            raise SolPlannerError(
                "Codex did not produce planner output."
            )

        try:
            plan = ExecutionPlan.model_validate_json(
                output_path.read_text(encoding="utf-8")
            )
            validate_plan(plan)
            return plan
        except PlanValidationError as exc:
            raise SolPlannerError(
                f"Invalid planner dependency graph: {exc}"
            ) from exc
        except Exception as exc:
            raise SolPlannerError(
                f"Invalid planner output: {exc}"
            ) from exc
