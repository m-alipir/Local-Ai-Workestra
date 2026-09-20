from __future__ import annotations

from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

        if not self.root.exists():
            raise WorkspaceError(f"Workspace does not exist: {self.root}")

        if not self.root.is_dir():
            raise WorkspaceError(f"Workspace is not a directory: {self.root}")

    def _resolve_safe(self, relative_path: str | Path) -> Path:
        path = (self.root / relative_path).resolve()

        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(
                f"Path escapes workspace: {relative_path}"
            ) from exc

        return path

    def read_text(self, relative_path: str | Path) -> str:
        path = self._resolve_safe(relative_path)

        if not path.exists():
            raise WorkspaceError(f"File does not exist: {relative_path}")

        if not path.is_file():
            raise WorkspaceError(f"Not a file: {relative_path}")

        return path.read_text(encoding="utf-8")

    def write_text(
        self,
        relative_path: str | Path,
        content: str,
    ) -> Path:
        path = self._resolve_safe(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")
        return path

    def exists(self, relative_path: str | Path) -> bool:
        return self._resolve_safe(relative_path).exists()
