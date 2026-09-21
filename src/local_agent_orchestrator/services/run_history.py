from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import shutil
from pathlib import Path

from local_agent_orchestrator.models.task import RunState, TaskStatus


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_TERMINAL = frozenset({TaskStatus.PASSED, TaskStatus.FAILED, TaskStatus.SKIPPED})


@dataclass(frozen=True, slots=True)
class RunHistoryEntry:
    run_id: str
    status: str
    updated_at: datetime
    path: Path
    archived: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "updated_at": self.updated_at.isoformat(),
            "path": str(self.path),
            "archived": self.archived,
        }


class RunHistory:
    """Control-owned run history actions scoped to one runs directory."""

    def __init__(self, runs_dir: str | Path) -> None:
        root = Path(runs_dir).expanduser().resolve()
        if root.is_symlink():
            raise ValueError("runs directory cannot be a symlink")
        self.runs_dir = root
        self.archive_dir = root / ".archive"

    def list(
        self,
        *,
        archived: bool = False,
        before: datetime | None = None,
    ) -> list[RunHistoryEntry]:
        root = self.archive_dir if archived else self.runs_dir
        if not root.is_dir() or root.is_symlink():
            return []
        entries: list[RunHistoryEntry] = []
        for child in sorted(root.iterdir(), key=lambda path: path.name):
            if child.name == ".archive" or not child.is_dir() or child.is_symlink():
                continue
            try:
                entry = self._entry(child, archived=archived)
            except (FileNotFoundError, ValueError):
                continue
            if before is None or entry.updated_at < self._cutoff(before):
                entries.append(entry)
        return sorted(
            entries,
            key=lambda entry: (entry.updated_at, entry.run_id),
            reverse=True,
        )

    def archive(
        self,
        run_id: str,
        *,
        before: datetime | None = None,
    ) -> Path:
        source = self._run_path(run_id, archived=False)
        entry = self._entry(source, archived=False)
        self._assert_eligible(entry, before)
        self._ensure_archive_dir()
        destination = self.archive_dir / run_id
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Archived run already exists: {run_id}")
        source.rename(destination)
        return destination

    def delete(
        self,
        run_id: str,
        *,
        before: datetime | None = None,
        archived: bool = False,
    ) -> None:
        source = self._run_path(run_id, archived=archived)
        entry = self._entry(source, archived=archived)
        self._assert_eligible(entry, before)
        shutil.rmtree(source)

    def _entry(self, path: Path, *, archived: bool) -> RunHistoryEntry:
        if path.is_symlink():
            raise ValueError("run entry cannot be a symlink")
        state_path = path / "state.json"
        if not path.is_dir() or state_path.is_symlink() or not state_path.is_file():
            raise FileNotFoundError(f"Run state not found: {path.name}")
        try:
            state = RunState.model_validate_json(
                state_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid run state: {path.name}") from exc
        if state.run_id != path.name:
            raise ValueError(f"Run id does not match directory: {path.name}")
        return RunHistoryEntry(
            run_id=state.run_id,
            status=state.status.value,
            updated_at=state.updated_at,
            path=path,
            archived=archived,
        )

    def _run_path(self, run_id: str, *, archived: bool) -> Path:
        if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run id")
        root = self.archive_dir if archived else self.runs_dir
        candidate = root / run_id
        if candidate.is_symlink():
            raise ValueError("run entry cannot be a symlink")
        if not self._inside(candidate, root):
            raise ValueError("Run path escapes the control directory")
        if not candidate.is_dir():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return candidate

    def _ensure_archive_dir(self) -> None:
        if self.archive_dir.exists() and self.archive_dir.is_symlink():
            raise ValueError("archive directory cannot be a symlink")
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        if not self._inside(self.archive_dir, self.runs_dir):
            raise ValueError("Archive path escapes the control directory")

    @staticmethod
    def _cutoff(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("before must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _assert_eligible(
        self,
        entry: RunHistoryEntry,
        before: datetime | None,
    ) -> None:
        if entry.status not in {status.value for status in _TERMINAL}:
            raise ValueError("Only terminal runs can be archived or deleted")
        if before is not None and entry.updated_at >= self._cutoff(before):
            raise ValueError("Run is not old enough for cleanup")

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        return True


def archive_run(
    runs_dir: str | Path,
    run_id: str,
    *,
    before: datetime | None = None,
) -> Path:
    return RunHistory(runs_dir).archive(run_id, before=before)


def delete_run(
    runs_dir: str | Path,
    run_id: str,
    *,
    before: datetime | None = None,
    archived: bool = False,
) -> None:
    RunHistory(runs_dir).delete(
        run_id,
        before=before,
        archived=archived,
    )
