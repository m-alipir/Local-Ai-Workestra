from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from secrets import token_hex

from local_agent_orchestrator.models.plan import ExecutionPlan
from local_agent_orchestrator.models.plan_intake import PlanIntakeResult
from local_agent_orchestrator.models.task import RunState
from local_agent_orchestrator.services.plan_runner import (
    PlanRunResult,
    run_execution_plan,
)
from local_agent_orchestrator.services.project_registry import (
    Project,
    ProjectRegistry,
)
from local_agent_orchestrator.services.plan_intake import (
    compile_plan as compile_markdown_plan,
    store_plan_markdown,
)
from local_agent_orchestrator.services.resume import (
    approve_waiting_task,
    resume_execution_plan,
)
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.run_diagnostics import collect_run_diagnostics
from local_agent_orchestrator.services.run_history import RunHistory


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ControlApplication:
    """Synchronous application boundary over the existing execution engine."""

    def __init__(self, registry: ProjectRegistry) -> None:
        self.registry = registry
        self.plans_dir = registry.path.parent / "plans"

    def create_project(
        self,
        name: str,
        workspace_root: str | Path,
        test_command: list[str] | tuple[str, ...],
        *,
        project_id: str | None = None,
        runs_dir: str | Path | None = None,
        analytics_dir: str | Path | None = None,
    ) -> Project:
        return self.registry.register(
            name,
            workspace_root,
            test_command,
            project_id=project_id,
            runs_dir=runs_dir,
            analytics_dir=analytics_dir,
        )

    def list_projects(self) -> list[Project]:
        return self.registry.list_projects()

    def get_project(self, project_id: str) -> Project:
        return self.registry.get(project_id)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        workspace_root: str | Path | None = None,
        test_command: list[str] | tuple[str, ...] | None = None,
    ) -> Project:
        return self.registry.update(
            project_id,
            name=name,
            workspace_root=workspace_root,
            test_command=test_command,
        )

    def update_project_request(
        self,
        project_id: str | dict[str, object],
        payload: dict[str, object] | None = None,
    ) -> Project:
        if payload is None:
            if not isinstance(project_id, dict):
                raise ValueError("project_id and request body are required.")
            payload = project_id
            project_id = payload.get("project_id")
        if not isinstance(project_id, str) or not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        editable = {"name", "path", "test_argv"}
        unknown = set(payload) - editable - {"project_id"}
        if unknown:
            raise ValueError(f"Unsupported project field: {sorted(unknown)[0]}")
        if "project_id" in payload and payload["project_id"] != project_id:
            raise ValueError("project_id does not match the project path.")
        if not any(field in payload for field in editable):
            raise ValueError("At least one project field is required.")

        name = payload.get("name")
        path = payload.get("path")
        test_argv = payload.get("test_argv")
        if "name" in payload and not isinstance(name, str):
            raise ValueError("name must be a string.")
        if "path" in payload and not isinstance(path, str):
            raise ValueError("path must be a string.")
        if "test_argv" in payload:
            if not isinstance(test_argv, list) or not test_argv:
                raise ValueError("test_argv must be a non-empty argv list.")
            if any(not isinstance(item, str) or not item for item in test_argv):
                raise ValueError("test_argv must contain only non-empty strings.")
        return self.update_project(
            project_id,
            name=name,
            workspace_root=path,
            test_command=test_argv,
        )

    def delete_project(self, project_id: str, payload: dict[str, object] | None = None) -> Project:
        if payload:
            raise ValueError("Project deletion does not accept request fields.")
        return self.registry.delete(project_id)

    def create_project_request(self, payload: dict[str, object]) -> Project:
        name = payload.get("name")
        workspace_root = payload.get("path")
        test_command = payload.get("test_argv")
        if not isinstance(name, str) or not isinstance(workspace_root, str):
            raise ValueError("name and path are required.")
        if not isinstance(test_command, list) or not test_command:
            raise ValueError("test_argv must be a non-empty argv list.")
        if any(not isinstance(item, str) or not item for item in test_command):
            raise ValueError("test_argv must contain only non-empty strings.")
        return self.create_project(name, workspace_root, test_command)

    def start_run(self, project_id: str, plan: ExecutionPlan) -> PlanRunResult:
        project = self.get_project(project_id)
        # Synchronous by design: no browser/request lifetime is stored or used.
        return run_execution_plan(
            plan=plan,
            workspace_root=project.workspace_root,
            test_command=list(project.test_command),
            runs_dir=project.runs_dir,
            analytics_dir=project.analytics_dir,
        )

    def start_plan_run(self, project_id: str, plan_id: str) -> PlanRunResult:
        record = self._load_plan(plan_id)
        if record["project_id"] != project_id:
            raise ValueError("Plan does not belong to the selected project.")
        if record.get("status") != "compiled":
            raise RuntimeError("Plan must compile successfully before execution.")
        plan = self._read_compiled_plan(plan_id)
        if plan is None:
            raise RuntimeError("Plan must compile successfully before execution.")
        return self.start_run(project_id, plan)

    def start_run_request(self, payload: dict[str, object]) -> PlanRunResult:
        project_id = payload.get("project_id")
        plan_id = payload.get("plan_id")
        if not isinstance(project_id, str) or not isinstance(plan_id, str):
            raise ValueError("project_id and plan_id are required.")
        return self.start_plan_run(project_id, plan_id)

    def import_plan(self, payload: dict[str, object]) -> dict[str, object]:
        project_id = payload.get("project_id")
        markdown = payload.get("markdown")
        if not isinstance(project_id, str) or not isinstance(markdown, str):
            raise ValueError("project_id and markdown are required.")
        self.get_project(project_id)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        plan_id = token_hex(8)
        markdown_path = self.plans_dir / f"{plan_id}.md"
        store_plan_markdown(markdown, markdown_path)
        record = {
            "id": plan_id,
            "project_id": project_id,
            "markdown_path": str(markdown_path),
            "status": "imported",
            "assumptions": [],
            "unresolved_issues": [],
            "error": None,
            "compiled_path": None,
        }
        self._write_plan_record(record)
        return record

    def get_plan(self, plan_id: str) -> dict[str, object]:
        return self._plan_view(self._load_plan(plan_id))

    def list_plans(self, project_id: str | None = None) -> list[dict[str, object]]:
        if project_id is not None:
            self.get_project(project_id)
        if not self.plans_dir.is_dir():
            return []
        plans = []
        for path in sorted(self.plans_dir.glob("*.record.json")):
            plan_id = path.name.removesuffix(".record.json")
            record = self._load_plan(plan_id)
            if project_id is None or record["project_id"] == project_id:
                plans.append(self._plan_view(record))
        return plans

    def compile_plan(
        self,
        plan_id: str,
        payload: dict[str, object] | None = None,
    ) -> PlanIntakeResult:
        record = self._load_plan(plan_id)
        force = self._force_compile(payload)
        if not force and record.get("status") == "compiled":
            plan = self._read_compiled_plan(plan_id)
            if plan is not None:
                return PlanIntakeResult(
                    status="compiled",
                    plan=plan,
                    assumptions=self._string_list(record.get("assumptions")),
                )
        markdown_path = Path(str(record["markdown_path"])).resolve()
        if not self._inside(markdown_path, self.plans_dir):
            raise ValueError("Stored plan path escapes the control plan directory.")
        markdown = markdown_path.read_text(encoding="utf-8")
        result = compile_markdown_plan(markdown)
        record.update({
            "status": result.status,
            "assumptions": list(result.assumptions),
            "unresolved_issues": list(result.unresolved_issues),
            "error": result.error,
            "compiled_path": None,
        })
        if result.status == "compiled" and result.plan is not None:
            self.plans_dir.mkdir(parents=True, exist_ok=True)
            compiled_path = self._write_compiled_plan(plan_id, result.plan)
            record["compiled_path"] = str(compiled_path)
        self._write_plan_record(record)
        return result

    def list_runs(
        self,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[RunState]:
        projects = (
            [self.get_project(project_id)]
            if project_id is not None
            else self.list_projects()
        )
        states: list[RunState] = []
        for project in projects:
            runs_dir = project.runs_dir
            if not runs_dir.is_dir():
                continue
            manager = RunStateManager(runs_dir)
            for child in runs_dir.iterdir():
                if child.is_dir() and (child / "state.json").is_file():
                    states.append(manager.load(child.name))
        if status is not None:
            states = [state for state in states if state.status.value == status]
        return sorted(
            states,
            key=lambda state: (state.updated_at, state.run_id),
            reverse=True,
        )

    def get_run(self, run_id: str, project_id: str | None = None) -> RunState:
        project, state = self._find_run(run_id, project_id)
        del project
        return state

    def get_run_diagnostics(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> dict[str, object]:
        project, _ = self._find_run(run_id, project_id)
        return collect_run_diagnostics(self._run_dir(project, run_id))

    def archive_run(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> dict[str, object]:
        project, _ = self._find_run(run_id, project_id)
        destination = RunHistory(project.runs_dir).archive(run_id)
        return {"run_id": run_id, "archived": True, "path": str(destination)}

    def delete_run(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> dict[str, object]:
        project, _ = self._find_run(run_id, project_id)
        RunHistory(project.runs_dir).delete(run_id)
        return {"run_id": run_id, "deleted": True}

    def approve_run(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
    ) -> str:
        project, _ = self._find_run(run_id, project_id)
        return approve_waiting_task(
            run_id=run_id,
            runs_dir=project.runs_dir,
            task_id=task_id,
        )

    def resume_run(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> PlanRunResult:
        project, _ = self._find_run(run_id, project_id)
        return resume_execution_plan(
            run_id=run_id,
            workspace_root=project.workspace_root,
            test_command=list(project.test_command),
            runs_dir=project.runs_dir,
            analytics_dir=project.analytics_dir,
        )

    def list_artifacts(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> tuple[str, ...]:
        project, _ = self._find_run(run_id, project_id)
        run_dir = self._run_dir(project, run_id)
        return tuple(
            sorted(
                str(path.relative_to(run_dir))
                for path in run_dir.rglob("*")
                if path.is_file() and self._inside(path, run_dir)
            )
        )

    def read_artifacts(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> list[dict[str, int | str]]:
        project, _ = self._find_run(run_id, project_id)
        run_dir = self._run_dir(project, run_id)
        return [
            {"name": name, "size": (run_dir / name).stat().st_size}
            for name in self.list_artifacts(run_id, project_id)
        ]

    def read_events(
        self,
        run_id: str,
        after_id: int = 0,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        if after_id < 0:
            raise ValueError("after_id must be non-negative.")
        self._find_run(run_id, project_id)
        try:
            content = self.read_artifact(run_id, "trajectory.jsonl", project_id)
        except FileNotFoundError:
            return []
        events: list[dict[str, object]] = []
        for event_id, line in enumerate(content.splitlines(), 1):
            if event_id <= after_id or not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                event_run_id = event.get("run_id")
                if event_run_id is not None and event_run_id != run_id:
                    continue
                event["id"] = event_id
                events.append(event)
        return events

    def read_artifact(
        self,
        run_id: str,
        artifact: str,
        project_id: str | None = None,
    ) -> str:
        project, _ = self._find_run(run_id, project_id)
        path = self._artifact_path(project, run_id, artifact)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {artifact}")
        return path.read_text(encoding="utf-8")

    def read_diff(
        self,
        run_id: str,
        project_id: str | None = None,
    ) -> dict[str, object]:
        project, _ = self._find_run(run_id, project_id)
        artifacts = self.list_artifacts(run_id, project_id)
        diff_names = [
            name for name in artifacts
            if name.endswith((".diff", ".patch"))
        ]
        if diff_names:
            content = self.read_artifact(run_id, diff_names[0], project_id)
        else:
            content = self._commit_diff(project, run_id)
        return {
            "available": diff_names,
            "content": content,
        }

    def _commit_diff(self, project: Project, run_id: str) -> str | None:
        metrics_dir = project.runs_dir / run_id / "metrics"
        commits: list[str] = []
        for path in sorted(metrics_dir.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            commit = value.get("commit") if isinstance(value, dict) else None
            if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{7,64}", commit):
                commits.append(commit)
        if not commits:
            return None
        result = subprocess.run(
            ["git", "show", "--format=", "--no-ext-diff", commits[-1]],
            cwd=project.workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout[:100_000] if result.returncode == 0 else None

    def _plan_view(self, record: dict[str, object]) -> dict[str, object]:
        plan_id = str(record["id"])
        markdown_path = self._markdown_path(record)
        plan = self._read_compiled_plan(plan_id)
        result = dict(record)
        result["markdown"] = markdown_path.read_text(encoding="utf-8")
        result["compiled"] = record.get("status") == "compiled" and plan is not None
        if result["compiled"] and plan is not None:
            result["plan"] = plan.model_dump(mode="json")
        return result

    def _markdown_path(self, record: dict[str, object]) -> Path:
        value = record.get("markdown_path")
        if not isinstance(value, str) or not value:
            raise RuntimeError("Invalid stored plan markdown path.")
        path = Path(value).resolve()
        if not self._inside(path, self.plans_dir):
            raise ValueError("Stored plan path escapes the control plan directory.")
        return path

    def _read_compiled_plan(self, plan_id: str) -> ExecutionPlan | None:
        path = (self.plans_dir / f"{plan_id}.json").resolve()
        if not self._inside(path, self.plans_dir):
            raise ValueError("Stored compiled plan path escapes the control plan directory.")
        if not path.is_file():
            return None
        try:
            return ExecutionPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Invalid stored compiled plan: {plan_id}") from exc

    def _write_compiled_plan(self, plan_id: str, plan: ExecutionPlan) -> Path:
        path = (self.plans_dir / f"{plan_id}.json").resolve()
        if not self._inside(path, self.plans_dir):
            raise ValueError("Stored compiled plan path escapes the control plan directory.")
        temporary = path.with_name(f".{path.name}.{token_hex(4)}.tmp")
        temporary.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def _write_plan_record(self, record: dict[str, object]) -> None:
        path = self.plans_dir / f"{record['id']}.record.json"
        temporary = path.with_name(f".{path.name}.{token_hex(4)}.tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _force_compile(payload: dict[str, object] | None) -> bool:
        if payload is None:
            return False
        if not isinstance(payload, dict):
            raise ValueError("Compile request must be a JSON object.")
        values = [payload[key] for key in ("force", "recompile") if key in payload]
        if any(not isinstance(value, bool) for value in values):
            raise ValueError("force and recompile must be booleans.")
        if len(values) == 2 and values[0] != values[1]:
            raise ValueError("force and recompile must agree.")
        return any(values)

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return []
        return list(value)

    def _find_run(
        self,
        run_id: str,
        project_id: str | None,
    ) -> tuple[Project, RunState]:
        self._validate_id(run_id, "run")
        projects = (
            [self.get_project(project_id)]
            if project_id is not None
            else self.list_projects()
        )
        found: list[tuple[Project, RunState]] = []
        for project in projects:
            try:
                found.append((project, RunStateManager(project.runs_dir).load(run_id)))
            except FileNotFoundError:
                continue
        if not found:
            raise FileNotFoundError(f"Run not found: {run_id}")
        if len(found) > 1:
            raise ValueError(f"Run id is ambiguous: {run_id}")
        return found[0]

    def _run_dir(self, project: Project, run_id: str) -> Path:
        path = project.runs_dir / run_id
        if not path.is_dir():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return path

    def _artifact_path(
        self,
        project: Project,
        run_id: str,
        artifact: str,
    ) -> Path:
        if not artifact or Path(artifact).is_absolute():
            raise ValueError("Artifact path must be relative.")
        run_dir = self._run_dir(project, run_id)
        path = (run_dir / artifact).resolve()
        if not self._inside(path, run_dir):
            raise ValueError("Artifact path escapes the run directory.")
        return path

    def _load_plan(self, plan_id: str) -> dict[str, object]:
        self._validate_id(plan_id, "plan")
        path = self.plans_dir / f"{plan_id}.record.json"
        if not path.is_file():
            raise FileNotFoundError(f"Plan not found: {plan_id}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid stored plan: {plan_id}") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"Invalid stored plan: {plan_id}")
        if record.get("id") != plan_id or not isinstance(record.get("project_id"), str):
            raise RuntimeError(f"Invalid stored plan: {plan_id}")
        return record

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_id(value: str, kind: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(f"Invalid {kind} id.")
