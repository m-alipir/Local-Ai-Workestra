from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from secrets import token_hex
from typing import Sequence


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

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

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
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Project name cannot be empty.")
        if isinstance(test_command, (str, bytes)):
            raise ValueError("test_command must be a sequence, not a shell string.")
        command = tuple(test_command)
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("test_command must be a non-empty sequence of strings.")

        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Project workspace is not a directory: {root}")

        identifier = project_id or token_hex(6)
        if not _SAFE_ID.fullmatch(identifier):
            raise ValueError("Project id contains unsafe characters.")
        projects = self.list_projects()
        if any(project.id == identifier for project in projects):
            raise ValueError(f"Project already exists: {identifier}")

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

    def _save(self, projects: list[Project]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{token_hex(4)}.tmp")
        temporary.write_text(
            json.dumps([project.to_dict() for project in projects], indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
