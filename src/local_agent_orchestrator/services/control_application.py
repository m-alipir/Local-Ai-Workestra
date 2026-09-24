from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex

from local_agent_orchestrator.models.plan import ExecutionPlan
from local_agent_orchestrator.models.plan_intake import PlanIntakeResult
from local_agent_orchestrator.models.project_spec import ProjectSpec
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
from local_agent_orchestrator.services.dependency_bootstrap import (
    VerificationBootstrapError,
    assert_verification_environment_supported,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_TRUSTED_VERIFIER = ["uv", "run", "pytest", "-q"]


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

    def bootstrap_python_project_request(self, payload: dict[str, object]) -> Project:
        name = payload.get("name")
        workspace_root = payload.get("path")
        if not isinstance(name, str) or not isinstance(workspace_root, str):
            raise ValueError("name and path are required.")
        if set(payload) - {"name", "path", "project_id", "profile"}:
            raise ValueError("Only name, path, project_id, and profile are supported for Python bootstrap.")
        project_id = payload.get("project_id")
        if project_id is not None and not isinstance(project_id, str):
            raise ValueError("project_id must be a string.")
        profile = payload.get("profile", "python")
        if not isinstance(profile, str):
            raise ValueError("profile must be a string.")
        return self.registry.bootstrap_python(name, workspace_root, project_id=project_id, profile=profile)

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
        test_command = payload.get("test_argv", list(_TRUSTED_VERIFIER))
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

    def start_plan_run(
        self,
        project_id: str | None,
        plan_id: str,
        compiled_revision: int,
    ) -> PlanRunResult:
        record = self._load_plan(plan_id)
        if record.get("project_id") is not None and record["project_id"] != project_id:
            raise ValueError("Plan does not belong to the selected project.")
        current = self._ensure_compiled_revision(record)
        if record.get("status") != "compiled" or current is None:
            raise RuntimeError("Plan must compile successfully before execution.")
        if compiled_revision != current["revision"]:
            raise RuntimeError("Plan revision is stale; reload the compiled plan before starting.")
        plan = self._read_compiled_revision(plan_id, compiled_revision)
        if plan is None:
            raise RuntimeError("Compiled plan revision is unavailable.")
        project = self._resolve_plan_project(plan, project_id)
        self._assert_verifier_ready(project)
        return run_execution_plan(
            plan=plan["plan"],
            workspace_root=project.workspace_root,
            test_command=list(project.test_command),
            runs_dir=project.runs_dir,
            analytics_dir=project.analytics_dir,
            plan_id=plan_id,
            compiled_revision=compiled_revision,
            compiled_digest=plan["plan_digest"],
            source_digest=plan["source_digest"],
            compiled_at=datetime.fromisoformat(plan["compiled_at"]),
        )

    def start_run_request(self, payload: dict[str, object]) -> PlanRunResult:
        project_id = payload.get("project_id")
        plan_id = payload.get("plan_id")
        compiled_revision = payload.get("compiled_revision")
        if project_id is not None and not isinstance(project_id, str):
            raise ValueError("project_id must be a string when provided.")
        if not isinstance(plan_id, str):
            raise ValueError("plan_id is required.")
        if not isinstance(compiled_revision, int) or isinstance(compiled_revision, bool):
            raise ValueError("compiled_revision must be an integer.")
        return self.start_plan_run(project_id, plan_id, compiled_revision)

    def assert_start_run_allowed(self, payload: dict[str, object]) -> None:
        project_id = payload.get("project_id")
        plan_id = payload.get("plan_id")
        revision = payload.get("compiled_revision")
        if project_id is not None and not isinstance(project_id, str):
            raise ValueError("project_id must be a string when provided.")
        if not isinstance(plan_id, str):
            raise ValueError("plan_id is required.")
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError("compiled_revision must be an integer.")
        record = self._load_plan(plan_id)
        if record.get("project_id") is not None and record["project_id"] != project_id:
            raise ValueError("Plan does not belong to the selected project.")
        current = self._ensure_compiled_revision(record)
        if record.get("status") != "compiled" or current is None:
            raise RuntimeError("Plan must compile successfully before execution.")
        if revision != current["revision"]:
            raise RuntimeError("Plan revision is stale; reload the compiled plan before starting.")
        project = self._resolve_plan_project(current, project_id)
        if project_id is None:
            payload["project_id"] = project.id
        self._assert_verifier_ready(project)
        RunStateManager(project.runs_dir).assert_execution_available()

    def _resolve_plan_project(
        self,
        compiled: dict[str, object],
        project_id: str | None,
    ) -> Project:
        if project_id is not None:
            project = self.get_project(project_id)
            spec = compiled.get("project_spec")
            if isinstance(spec, ProjectSpec) and spec.intent == "new":
                expected_root = self._project_spec_workspace(spec)
                if project.id != spec.slug or project.workspace_root != expected_root:
                    raise RuntimeError("Greenfield plan must start in its Workestra-created project under projects_root.")
            return project
        spec = compiled.get("project_spec")
        if not isinstance(spec, ProjectSpec) or spec.intent != "new":
            raise ValueError("project_id is required for an existing-project plan.")
        raise RuntimeError("Create the project before starting this greenfield plan.")

    def project_creation_eligibility(
        self,
        plan_id: str,
        compiled_revision: int,
    ) -> dict[str, object]:
        record = self._load_plan(plan_id)
        current = self._ensure_compiled_revision(record)
        reasons: list[str] = []
        if record.get("status") != "compiled" or current is None:
            issues = record.get("unresolved_issues")
            if isinstance(issues, list):
                reasons.extend(item for item in issues if isinstance(item, str))
            error = record.get("error")
            if isinstance(error, str) and error:
                reasons.append(error)
            if not reasons:
                reasons.append("Plan must compile successfully before creating a project.")
        elif compiled_revision != current["revision"]:
            reasons.append("Plan revision is stale; reload the compiled plan before creating a project.")

        spec = current.get("project_spec") if current is not None else None
        if current is not None and not isinstance(spec, ProjectSpec):
            reasons.append("Compiled plan has no valid ProjectSpec.")
        elif isinstance(spec, ProjectSpec):
            if spec.intent != "new":
                reasons.append("ProjectSpec targets an existing project.")
            reasons.extend(
                f"Research required: {item.topic} — {item.reason}"
                for item in spec.research_requirements
                if item.blocking
            )
            if spec.bootstrap_profile not in {"python", "fastapi"}:
                reasons.append("ProjectSpec has no trusted bootstrap profile.")
            supported = {"python", "fastapi", "sqlite", "sqlalchemy", "pytest", "api-testing"}
            unsupported = sorted(set(spec.capabilities) - supported)
            if unsupported:
                reasons.append("No trusted Workestra capability is available for: " + ", ".join(unsupported) + ".")
            if spec.bootstrap_profile in {"python", "fastapi"}:
                missing_tools = [name for name in ("git", "uv") if shutil.which(name) is None]
                if missing_tools:
                    reasons.append("Trusted bootstrap requires unavailable tools: " + ", ".join(missing_tools) + ".")
            if not isinstance(spec.workspace_root, str):
                reasons.append("ProjectSpec has no safe default workspace.")
            else:
                try:
                    root = self._project_spec_workspace(spec)
                except (ValueError, RuntimeError) as exc:
                    reasons.append(str(exc))
                else:
                    if root.is_symlink():
                        reasons.append("ProjectSpec workspace cannot be a symlink.")
                    elif root.exists() and (not root.is_dir() or any(root.iterdir())):
                        reasons.append(f"ProjectSpec workspace must be empty or missing: {root}")
                    if current is not None:
                        source = self._markdown_path(record).read_text(encoding="utf-8")
                        if current["source_digest"] != self._digest(source):
                            reasons.append("Source Markdown changed since the latest compiled revision; recompile before creating a project.")
                    for project in self.registry.list_projects():
                        if record.get("project_id") == project.id and project.id == spec.slug and project.workspace_root.resolve() == root:
                            continue
                        if project.workspace_root.resolve() == root:
                            reasons.append(f"ProjectSpec workspace is already registered to project {project.id}.")
            if record.get("project_id") is None and any(project.id == spec.slug for project in self.registry.list_projects()):
                reasons.append(f"Project already exists: {spec.slug}")

        return {
            "eligible": not reasons,
            "reasons": list(dict.fromkeys(reasons)),
            "plan_id": plan_id,
            "compiled_revision": current["revision"] if current is not None else None,
            "project_spec": spec.model_dump(mode="json") if isinstance(spec, ProjectSpec) else None,
        }

    def create_project_from_plan(self, plan_id: str, compiled_revision: int) -> Project:
        record = self._load_plan(plan_id)
        current = self._ensure_compiled_revision(record)
        if record.get("status") == "compiled" and current is not None:
            if compiled_revision != current["revision"]:
                raise RuntimeError("Plan revision is stale; reload the compiled plan before creating a project.")
            spec = current.get("project_spec")
            if isinstance(spec, ProjectSpec) and record.get("project_id") is not None:
                if record["project_id"] != spec.slug or spec.workspace_root is None:
                    raise RuntimeError("Compiled plan is bound to a different project.")
                project = self.registry.get(spec.slug)
                expected_root = self._project_spec_workspace(spec)
                if project.workspace_root != expected_root or project.test_command != tuple(_TRUSTED_VERIFIER):
                    raise RuntimeError("Bound project does not match the compiled ProjectSpec.")
                return project
        eligibility = self.project_creation_eligibility(plan_id, compiled_revision)
        if not eligibility["eligible"]:
            raise RuntimeError("Project creation is blocked: " + "; ".join(eligibility["reasons"]))
        compiled = self._read_compiled_revision(plan_id, compiled_revision)
        spec = compiled.get("project_spec") if compiled is not None else None
        if not isinstance(spec, ProjectSpec) or spec.workspace_root is None:
            raise RuntimeError("Compiled ProjectSpec is unavailable.")
        root = self._project_spec_workspace(spec)
        project = self.registry.bootstrap_python(
            spec.name,
            root,
            project_id=spec.slug,
            profile=spec.bootstrap_profile or "python",
        )
        record = self._load_plan(plan_id)
        record["project_id"] = project.id
        self._write_plan_record(record)
        return project

    def _project_spec_workspace(self, spec: ProjectSpec) -> Path:
        if not isinstance(spec.workspace_root, str):
            raise RuntimeError("ProjectSpec has no safe default workspace.")
        requested = Path(spec.workspace_root).expanduser()
        if not requested.is_absolute():
            # Revisions written before projects_root became explicit used this prefix.
            if requested.parts[:1] == ("projects",):
                requested = Path(*requested.parts[1:])
            requested = self.registry.projects_root / requested
        if requested.is_symlink():
            raise RuntimeError("ProjectSpec workspace cannot be a symlink.")
        root = requested.resolve()
        base = self.registry.projects_root.resolve()
        if root == base or not self._inside(root, base):
            raise RuntimeError("ProjectSpec workspace escapes the configured projects root.")
        return root

    @staticmethod
    def _assert_verifier_ready(project: Project) -> None:
        try:
            assert_verification_environment_supported(
                project.workspace_root,
                list(project.test_command),
            )
        except VerificationBootstrapError as exc:
            raise RuntimeError(
                f"Verification environment unavailable [{exc.code}]: {exc.detail}"
            ) from exc

    def import_plan(self, payload: dict[str, object]) -> dict[str, object]:
        project_id = payload.get("project_id")
        markdown = payload.get("markdown")
        if project_id is not None and not isinstance(project_id, str):
            raise ValueError("project_id must be a string when provided.")
        if not isinstance(markdown, str):
            raise ValueError("markdown is required.")
        if project_id is not None:
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
            "project_spec": None,
            "compiled_path": None,
            "compiled_revision": None,
            "compiled_digest": None,
            "source_digest": self._digest(markdown),
            "compiled_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "compile_attempts": [],
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

    def list_plan_history(self) -> list[dict[str, object]]:
        groups: dict[str, dict[str, object]] = {}
        for plan in self.list_plans():
            digest = self._digest(str(plan["markdown"]))
            group = groups.setdefault(digest, {
                "source_digest": digest,
                "markdown": plan["markdown"],
                "title": next((line.lstrip("# ").strip() for line in str(plan["markdown"]).splitlines() if line.strip()), "Untitled plan"),
                "plan_ids": [],
                "attempts": [],
                "revisions": [],
                "latest_attempt": None,
                "latest_good": None,
            })
            plan_id = str(plan["id"])
            group["plan_ids"].append(plan_id)
            attempts = plan.get("compile_attempts", [])
            group["attempts"].extend({**attempt, "plan_id": plan_id} for attempt in attempts)
            group["revisions"].extend({**revision, "plan_id": plan_id} for revision in plan.get("compiled_revisions", []))
        for group in groups.values():
            group["attempts"].sort(key=lambda item: item.get("finished_at") or "")
            group["revisions"].sort(key=lambda item: (item.get("compiled_at") or "", item.get("revision") or 0))
            if group["attempts"]:
                group["latest_attempt"] = group["attempts"][-1]
            reusable = [revision for revision in group["revisions"] if revision.get("reusable")]
            if reusable:
                latest = max(reusable, key=lambda item: item.get("compiled_at") or "")
                group["latest_good"] = {"plan_id": latest["plan_id"], "revision": latest["revision"]}
        return sorted(groups.values(), key=lambda group: group["latest_attempt"].get("finished_at", "") if group["latest_attempt"] else "", reverse=True)

    def compile_plan(
        self,
        plan_id: str,
        payload: dict[str, object] | None = None,
    ) -> PlanIntakeResult:
        record = self._load_plan(plan_id)
        force = self._force_compile(payload)
        current = self._ensure_compiled_revision(record)
        markdown_path = self._markdown_path(record)
        markdown = markdown_path.read_text(encoding="utf-8")
        source_digest = self._digest(markdown)
        if (
            not force
            and record.get("status") == "compiled"
            and current is not None
            and current["source_digest"] == source_digest
        ):
            return PlanIntakeResult(
                status="compiled",
                plan=current["plan"],
                project_spec=current.get("project_spec"),
                assumptions=self._string_list(record.get("assumptions")),
                compiled_revision=current["revision"],
                compiled_digest=current["plan_digest"],
                source_digest=current["source_digest"],
                compiled_at=current["compiled_at"],
            )
        attempted_at = datetime.now(timezone.utc).isoformat()
        projects = self.registry.list_projects()
        bound = next((project for project in projects if project.id == record.get("project_id")), None)
        result = compile_markdown_plan(
            markdown,
            projects_root=self.registry.projects_root,
            occupied_workspace_paths=[project.workspace_root for project in projects if bound is None or project.id != bound.id],
            occupied_project_ids=[project.id for project in projects if bound is None or project.id != bound.id],
            bound_project_id=bound.id if bound else None,
            bound_workspace_root=bound.workspace_root if bound else None,
        )
        # Re-read before committing: a concurrent successful compile must not be
        # overwritten by this attempt's failure.
        record = self._load_plan(plan_id)
        attempts = record.get("compile_attempts")
        if not isinstance(attempts, list):
            attempts = []
            previous = record.get("last_compile_attempt")
            if isinstance(previous, dict):
                attempts.append(previous)
        attempt = {
            "status": result.status,
            "started_at": attempted_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_digest": source_digest,
            "error": result.error,
            "unresolved_issues": list(result.unresolved_issues),
        }
        attempts.append(attempt)
        record["compile_attempts"] = attempts
        record["last_compile_attempt"] = attempt
        if result.status == "compiled" and result.plan is not None:
            self.plans_dir.mkdir(parents=True, exist_ok=True)
            revision = self._next_compiled_revision(record)
            current = self._write_compiled_revision(
                plan_id,
                revision,
                result.plan,
                source_digest,
                result.project_spec,
            )
            record.update({
                "compiled_path": current["path"],
                "compiled_revision": revision,
                "compiled_digest": current["plan_digest"],
                "source_digest": source_digest,
                "compiled_at": current["compiled_at"],
                "status": "compiled",
                "assumptions": list(result.assumptions),
                "unresolved_issues": list(result.unresolved_issues),
                "error": None,
                "project_spec": (
                    result.project_spec.model_dump(mode="json")
                    if result.project_spec is not None
                    else None
                ),
            })
        else:
            has_good_revision = self._ensure_compiled_revision(record) is not None
            if not has_good_revision:
                record.update({
                    "status": result.status,
                    "assumptions": list(result.assumptions),
                    "unresolved_issues": list(result.unresolved_issues),
                    "error": result.error,
                    "project_spec": (
                        result.project_spec.model_dump(mode="json")
                        if result.project_spec is not None
                        else None
                    ),
                    "compiled_path": None,
                    "compiled_revision": None,
                    "compiled_digest": None,
                    "source_digest": source_digest,
                    "compiled_at": None,
                })
            current = None
        self._write_plan_record(record)
        if current is None:
            return result
        return result.model_copy(update={
            "compiled_revision": current["revision"],
            "compiled_digest": current["plan_digest"],
            "source_digest": current["source_digest"],
            "compiled_at": current["compiled_at"],
        })

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

    def assert_resume_run_allowed(self, run_id: str, project_id: str | None = None) -> None:
        project, state = self._find_run(run_id, project_id)
        if state.status.value not in {"pending", "running"}:
            raise RuntimeError("Run must be approved and pending, or be an interrupted running run, before it can be resumed.")
        RunStateManager(project.runs_dir).assert_execution_available()

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
        markdown_path = self._markdown_path(record)
        current = self._ensure_compiled_revision(record)
        result = dict(record)
        result["markdown"] = markdown_path.read_text(encoding="utf-8")
        result["compiled"] = record.get("status") == "compiled" and current is not None
        attempts = record.get("compile_attempts")
        if not isinstance(attempts, list):
            attempts = [record["last_compile_attempt"]] if isinstance(record.get("last_compile_attempt"), dict) else []
        result["compile_attempts"] = attempts
        revisions = []
        revision_dir = self.plans_dir / f"{record['id']}.revisions"
        for path in sorted(revision_dir.glob("*.json")) if revision_dir.is_dir() else []:
            try:
                revision = int(path.stem)
                data = self._read_compiled_revision(str(record["id"]), revision)
            except (ValueError, RuntimeError):
                continue
            if data is None:
                continue
            active = current is not None and current["revision"] == revision and record.get("status") == "compiled"
            same_source = data["source_digest"] == self._digest(str(result["markdown"]))
            revisions.append({
                "revision": revision,
                "compiled_at": data["compiled_at"],
                "plan_digest": data["plan_digest"],
                "active": active,
                "reusable": active and same_source,
                "reason": None if active and same_source else ("Source Markdown changed; recompile before reuse/start." if not same_source else "A newer successful revision is active."),
            })
        result["compiled_revisions"] = revisions
        if result["compiled"] and current is not None:
            result["plan"] = current["plan"].model_dump(mode="json")
            if current.get("project_spec") is not None:
                result["project_spec"] = current["project_spec"].model_dump(mode="json")
        elif isinstance(record.get("project_spec"), dict):
            result["project_spec"] = ProjectSpec.model_validate(
                record["project_spec"]
            ).model_dump(mode="json")
        return result

    def _markdown_path(self, record: dict[str, object]) -> Path:
        value = record.get("markdown_path")
        if not isinstance(value, str) or not value:
            raise RuntimeError("Invalid stored plan markdown path.")
        path = Path(value).resolve()
        if not self._inside(path, self.plans_dir):
            raise ValueError("Stored plan path escapes the control plan directory.")
        return path

    def _read_compiled_revision(
        self,
        plan_id: str,
        revision: int,
    ) -> dict[str, object] | None:
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("Compiled plan revision is invalid.")
        path = self._revision_path(plan_id, revision)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("revision payload must be an object")
            if value.get("plan_id") != plan_id or value.get("revision") != revision:
                raise ValueError("revision identity does not match its path")
            plan = ExecutionPlan.model_validate(value.get("plan"))
            project_spec_value = value.get("project_spec")
            project_spec = (
                None
                if project_spec_value is None
                else ProjectSpec.model_validate(project_spec_value)
            )
            plan_digest = value.get("plan_digest")
            project_spec_digest = value.get("project_spec_digest")
            source_digest = value.get("source_digest")
            compiled_at = value.get("compiled_at")
            if (
                not all(isinstance(item, str) and item for item in (
                    plan_digest,
                    source_digest,
                    compiled_at,
                ))
                or plan_digest != self._digest(self._plan_text(plan))
                or (
                    project_spec is not None
                    and project_spec_digest != self._digest(self._project_spec_text(project_spec))
                )
            ):
                raise ValueError("revision digest is invalid")
            datetime.fromisoformat(compiled_at)
            return {
                "path": str(path),
                "revision": revision,
                "plan": plan,
                "project_spec": project_spec,
                "plan_digest": plan_digest,
                "project_spec_digest": project_spec_digest,
                "source_digest": source_digest,
                "compiled_at": compiled_at,
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid stored compiled plan revision: {plan_id}/{revision}") from exc

    def _write_compiled_revision(
        self,
        plan_id: str,
        revision: int,
        plan: ExecutionPlan,
        source_digest: str,
        project_spec: ProjectSpec | None = None,
    ) -> dict[str, object]:
        path = self._revision_path(plan_id, revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        plan_text = self._plan_text(plan)
        compiled_at = datetime.now(timezone.utc).isoformat()
        value = {
            "plan_id": plan_id,
            "revision": revision,
            "compiled_at": compiled_at,
            "source_digest": source_digest,
            "plan_digest": self._digest(plan_text),
            "plan": plan.model_dump(mode="json"),
        }
        if project_spec is not None:
            value["project_spec"] = project_spec.model_dump(mode="json")
            value["project_spec_digest"] = self._digest(self._project_spec_text(project_spec))
        temporary = path.with_name(f".{path.name}.{token_hex(4)}.tmp")
        try:
            temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            os.link(temporary, path)
        except FileExistsError as exc:
            raise RuntimeError(f"Compiled plan revision already exists: {plan_id}/{revision}") from exc
        finally:
            temporary.unlink(missing_ok=True)
        stored = self._read_compiled_revision(plan_id, revision)
        if stored is None:
            raise RuntimeError(f"Compiled plan revision could not be read: {plan_id}/{revision}")
        return stored

    def _ensure_compiled_revision(self, record: dict[str, object]) -> dict[str, object] | None:
        revision = record.get("compiled_revision")
        plan_id = str(record["id"])
        if isinstance(revision, int) and not isinstance(revision, bool) and revision > 0:
            try:
                current = self._read_compiled_revision(plan_id, revision)
                if current is None:
                    return self._invalidate_compiled_revision(record, revision)
                for record_field, revision_field in (
                    ("compiled_digest", "plan_digest"),
                    ("source_digest", "source_digest"),
                    ("compiled_at", "compiled_at"),
                ):
                    if (
                        record.get(record_field) is not None
                        and record[record_field] != current[revision_field]
                    ):
                        raise ValueError(
                            "stored revision metadata does not match the artifact"
                        )
                return current
            except (RuntimeError, ValueError):
                return self._invalidate_compiled_revision(record, revision)
        if record.get("status") in {"failed", "rejected"}:
            digest = self._digest(self._markdown_path(record).read_text(encoding="utf-8"))
            revision_dir = self.plans_dir / f"{plan_id}.revisions"
            for path in sorted(revision_dir.glob("*.json"), key=lambda item: int(item.stem) if item.stem.isdigit() else 0, reverse=True):
                if not path.stem.isdigit() or int(path.stem) < 1:
                    continue
                try:
                    current = self._read_compiled_revision(plan_id, int(path.stem))
                except RuntimeError:
                    continue
                if current is None or current["source_digest"] != digest:
                    continue
                previous_error = record.get("error")
                existing_attempt = record.get("last_compile_attempt")
                if not isinstance(existing_attempt, dict) or existing_attempt.get("status") == "compiled":
                    record["last_compile_attempt"] = {
                        "status": record["status"],
                        "error": previous_error,
                        "unresolved_issues": self._string_list(record.get("unresolved_issues")),
                    }
                record.update({
                    "status": "compiled",
                    "compiled_path": current["path"],
                    "compiled_revision": current["revision"],
                    "compiled_digest": current["plan_digest"],
                    "source_digest": current["source_digest"],
                    "compiled_at": current["compiled_at"],
                    "project_spec": current["project_spec"].model_dump(mode="json") if current["project_spec"] else None,
                    "error": None,
                    "unresolved_issues": [],
                })
                self._write_plan_record(record)
                return current
        legacy_path = self.plans_dir / f"{plan_id}.json"
        if record.get("status") != "compiled" or not legacy_path.is_file():
            if record.get("status") == "compiled":
                return self._invalidate_compiled_revision(record, None)
            return None
        try:
            plan = ExecutionPlan.model_validate_json(legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._invalidate_compiled_revision(record, None)
        current = self._write_compiled_revision(
            plan_id,
            1,
            plan,
            self._digest(self._markdown_path(record).read_text(encoding="utf-8")),
        )
        record.update({
            "compiled_path": current["path"],
            "compiled_revision": 1,
            "compiled_digest": current["plan_digest"],
            "source_digest": current["source_digest"],
            "compiled_at": current["compiled_at"],
        })
        self._write_plan_record(record)
        return current

    def _invalidate_compiled_revision(
        self,
        record: dict[str, object],
        revision: int | None,
    ) -> None:
        plan_id = str(record["id"])
        invalidated = record.get("invalidated_compiled_revisions")
        history = list(invalidated) if isinstance(invalidated, list) else []
        if revision is not None and revision not in history:
            history.append(revision)
        record.update({
            "status": "needs_recompile",
            "compiled_path": None,
            "compiled_revision": None,
            "compiled_digest": None,
            "compiled_at": None,
            "error": (
                f"Stored compiled plan revision {plan_id}/{revision} is incompatible; "
                "recompile required."
                if revision is not None
                else "Stored compiled plan is unavailable or invalid; recompile required."
            ),
            "invalidated_compiled_revisions": history,
        })
        self._write_plan_record(record)
        return None

    def _revision_path(self, plan_id: str, revision: int) -> Path:
        path = (self.plans_dir / f"{plan_id}.revisions" / f"{revision}.json").resolve()
        if not self._inside(path, self.plans_dir):
            raise ValueError("Stored compiled plan path escapes the control plan directory.")
        return path

    @staticmethod
    def _plan_text(plan: ExecutionPlan) -> str:
        return plan.model_dump_json(indent=2) + "\n"

    @staticmethod
    def _project_spec_text(project_spec: ProjectSpec) -> str:
        return project_spec.model_dump_json(indent=2) + "\n"

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _next_compiled_revision(self, record: dict[str, object]) -> int:
        revisions: set[int] = set()
        revision = record.get("compiled_revision")
        if isinstance(revision, int) and not isinstance(revision, bool) and revision > 0:
            revisions.add(revision)
        invalidated = record.get("invalidated_compiled_revisions")
        if isinstance(invalidated, list):
            revisions.update(
                item for item in invalidated
                if isinstance(item, int) and not isinstance(item, bool) and item > 0
            )
        revision_dir = self.plans_dir / f"{record['id']}.revisions"
        if revision_dir.is_dir():
            revisions.update(
                int(path.stem)
                for path in revision_dir.glob("*.json")
                if path.stem.isdigit() and int(path.stem) > 0
            )
        return max(revisions, default=0) + 1

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
        if record.get("id") != plan_id or (
            record.get("project_id") is not None
            and not isinstance(record.get("project_id"), str)
        ):
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
