from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from secrets import token_hex
from typing import Sequence

from local_agent_orchestrator.services.project_bootstrap import (
    bootstrap_python_project,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    workspace_root: Path
    test_command: tuple[str, ...]
    runs_dir: Path
    analytics_dir: Path

    def to_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["workspace_root"] = str(self.workspace_root)
        values["path"] = str(self.workspace_root)
        values["test_command"] = list(self.test_command)
        values["runs_dir"] = str(self.runs_dir)
        values["analytics_dir"] = str(self.analytics_dir)
        return values

    @classmethod
    def from_dict(cls, values: dict[str, object]) -> Project:
        return cls(
            id=str(values["id"]),
            name=str(values["name"]),
            workspace_root=Path(str(values["workspace_root"])),
            test_command=tuple(str(item) for item in values["test_command"]),
            runs_dir=Path(str(values["runs_dir"])),
            analytics_dir=Path(str(values["analytics_dir"])),
        )


class ProjectRegistry:
    """Small durable index of projects; run state remains in each run directory."""

    def __init__(
        self,
        path: str | Path,
        *,
        projects_root: str | Path | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.projects_root = Path(
            projects_root if projects_root is not None else self.path.parent / "projects"
        ).expanduser().resolve()

    def register(
        self,
        name: str,
        workspace_root: str | Path,
        test_command: Sequence[str],
        *,
        project_id: str | None = None,
        runs_dir: str | Path | None = None,
        analytics_dir: str | Path | None = None,
    ) -> Project:
        clean_name = self._name(name)
        command = self._command(test_command)
        root = self._workspace(workspace_root)

        identifier = project_id or token_hex(6)
        if not _SAFE_ID.fullmatch(identifier):
            raise ValueError("Project id contains unsafe characters.")
        projects = self.list_projects()
        if any(project.id == identifier for project in projects):
            raise ValueError(f"Project already exists: {identifier}")
        self._assert_workspace_not_registered(root, projects)

        project = Project(
            id=identifier,
            name=clean_name,
            workspace_root=root,
            test_command=command,
            runs_dir=self._resolve_path(
                root,
                runs_dir
                if runs_dir is not None
                else self.path.parent / "runs" / identifier,
            ),
            analytics_dir=self._resolve_path(
                root,
                analytics_dir
                if analytics_dir is not None
                else self.path.parent / "analytics" / identifier,
            ),
        )
        self._save([*projects, project])
        return project

    def bootstrap_python(
        self,
        name: str,
        workspace_root: str | Path,
        *,
        project_id: str | None = None,
        runs_dir: str | Path | None = None,
        analytics_dir: str | Path | None = None,
        profile: str = "python",
    ) -> Project:
        """Create and register the one supported Python project baseline."""

        clean_name = self._name(name)
        if project_id is not None and not _SAFE_ID.fullmatch(project_id):
            raise ValueError("Project id contains unsafe characters.")
        if project_id is not None and any(
            project.id == project_id for project in self.list_projects()
        ):
            raise ValueError(f"Project already exists: {project_id}")
        if isinstance(workspace_root, str) and not workspace_root.strip():
            raise ValueError("Project workspace cannot be empty.")
        requested_workspace = Path(workspace_root).expanduser()
        if requested_workspace.is_symlink():
            raise ValueError("Project workspace cannot be a symlink.")
        workspace = requested_workspace.resolve()
        self._assert_workspace_not_registered(workspace, self.list_projects())
        result = bootstrap_python_project(workspace, name, profile=profile)
        return self.register(
            clean_name,
            result.workspace_root,
            result.test_command,
            project_id=project_id,
            runs_dir=runs_dir,
            analytics_dir=analytics_dir,
        )

    def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        workspace_root: str | Path | None = None,
        test_command: Sequence[str] | None = None,
    ) -> Project:
        project = self.get(project_id)
        projects = self.list_projects()
        root = project.workspace_root if workspace_root is None else self._workspace(workspace_root)
        self._assert_workspace_not_registered(root, projects, excluding=project_id)
        updated = Project(
            id=project.id,
            name=project.name if name is None else self._name(name),
            workspace_root=(
                project.workspace_root
                if workspace_root is None
                else root
            ),
            test_command=(
                project.test_command
                if test_command is None
                else self._command(test_command)
            ),
            # These are control-owned paths. Keep them stable when a target
            # workspace is edited so run and analytics history remains usable.
            runs_dir=project.runs_dir,
            analytics_dir=project.analytics_dir,
        )
        self._save([updated if item.id == project_id else item for item in self.list_projects()])
        return updated

    def delete(self, project_id: str) -> Project:
        """Remove a project index entry without touching its workspace or history."""
        project = self.get(project_id)
        self._save([item for item in self.list_projects() if item.id != project_id])
        return project

    def list_projects(self) -> list[Project]:
        if not self.path.exists():
            return []
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid project registry: {self.path}") from exc
        if not isinstance(values, list):
            raise ValueError(f"Invalid project registry: {self.path}")
        return [Project.from_dict(item) for item in values]

    def get(self, project_id: str) -> Project:
        if not _SAFE_ID.fullmatch(project_id):
            raise KeyError(f"Project not found: {project_id}")
        for project in self.list_projects():
            if project.id == project_id:
                return project
        raise KeyError(f"Project not found: {project_id}")

    @staticmethod
    def _resolve_path(root: Path, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (root / path).resolve()

    @staticmethod
    def _name(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Project name cannot be empty.")
        return value.strip()

    @staticmethod
    def _command(value: Sequence[str]) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)):
            raise ValueError("test_command must be a sequence, not a shell string.")
        command = tuple(value)
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("test_command must be a non-empty sequence of strings.")
        first = command[0].lower()
        if first in {"pytest", "pytest.exe"}:
            return command
        if (
            first in {"python", "python3", "python.exe", "python3.exe"}
            and len(command) >= 3
            and command[1] == "-m"
            and command[2].lower() == "pytest"
        ):
            return command
        if (
            first in {"uv", "uv.exe"}
            and len(command) >= 3
            and command[1] == "run"
            and command[2].lower() == "pytest"
        ):
            return command
        raise ValueError(
            "test_command must use a supported verifier profile (pytest, python -m pytest, or uv run pytest)."
        )

    @staticmethod
    def _workspace(value: str | Path) -> Path:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Project workspace cannot be empty.")
        root = Path(value).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Project workspace is not a directory: {root}")
        return root

    @staticmethod
    def _assert_workspace_not_registered(
        workspace_root: Path,
        projects: list[Project],
        *,
        excluding: str | None = None,
    ) -> None:
        if any(
            project.id != excluding and project.workspace_root.resolve() == workspace_root.resolve()
            for project in projects
        ):
            raise ValueError(f"Project workspace path is already registered: {workspace_root}")

    def _save(self, projects: list[Project]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{token_hex(4)}.tmp")
        temporary.write_text(
            json.dumps([project.to_dict() for project in projects], indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
