from __future__ import annotations

import subprocess
from pathlib import Path

from local_agent_orchestrator.models.tool_action import (
    ToolAction,
    ToolObservation,
)


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}

MAX_READ_BYTES = 200_000


class RepoToolError(RuntimeError):
    pass


class RepoTools:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve()

        if not self.root.exists():
            raise RepoToolError(
                f"Workspace does not exist: {self.root}"
            )

    def _resolve(self, relative_path: str | None) -> Path:
        relative_path = relative_path or "."

        candidate = (
            self.root / relative_path
        ).resolve()

        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise RepoToolError(
                "Path escapes workspace root."
            ) from exc

        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(
            self.root
        ).as_posix()

    def execute(
        self,
        action: ToolAction,
    ) -> ToolObservation:
        try:
            if action.tool == "list_files":
                content = self.list_files(
                    action.path,
                    action.max_results,
                )

            elif action.tool == "search_text":
                if not action.query:
                    raise RepoToolError(
                        "search_text requires query"
                    )

                content = self.search_text(
                    action.query,
                    action.path,
                    action.max_results,
                )

            elif action.tool == "read_file":
                if not action.path:
                    raise RepoToolError(
                        "read_file requires path"
                    )

                content = self.read_file(
                    action.path
                )

            elif action.tool == "git_status":
                content = self.git_status()

            elif action.tool == "git_diff":
                content = self.git_diff()

            else:
                raise RepoToolError(
                    f"Unsupported tool: {action.tool}"
                )

            return ToolObservation(
                tool=action.tool,
                ok=True,
                content=content,
            )

        except Exception as exc:
            return ToolObservation(
                tool=action.tool,
                ok=False,
                content=str(exc),
            )

    def list_files(
        self,
        path: str | None = None,
        max_results: int = 50,
    ) -> str:
        base = self._resolve(path)

        if not base.exists():
            raise RepoToolError(
                f"Path does not exist: {path}"
            )

        if base.is_file():
            return self._relative(base)

        results: list[str] = []

        for item in sorted(base.rglob("*")):
            if any(
                part in IGNORED_DIRS
                for part in item.relative_to(
                    self.root
                ).parts
            ):
                continue

            if not item.is_file():
                continue

            results.append(
                self._relative(item)
            )

            if len(results) >= max_results:
                break

        return "\n".join(results)

    def read_file(
        self,
        path: str,
    ) -> str:
        target = self._resolve(path)

        if not target.exists():
            raise RepoToolError(
                f"File does not exist: {path}"
            )

        if not target.is_file():
            raise RepoToolError(
                f"Not a file: {path}"
            )

        size = target.stat().st_size

        if size > MAX_READ_BYTES:
            raise RepoToolError(
                f"File too large to read safely: {size} bytes"
            )

        try:
            return target.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError as exc:
            raise RepoToolError(
                "Binary or non-UTF-8 file cannot be read."
            ) from exc

    def search_text(
        self,
        query: str,
        path: str | None = None,
        max_results: int = 50,
    ) -> str:
        base = self._resolve(path)

        if not base.exists():
            raise RepoToolError(
                f"Path does not exist: {path}"
            )

        files = (
            [base]
            if base.is_file()
            else base.rglob("*")
        )

        matches: list[str] = []

        for file in files:
            if not file.is_file():
                continue

            relative_parts = file.relative_to(
                self.root
            ).parts

            if any(
                part in IGNORED_DIRS
                for part in relative_parts
            ):
                continue

            if file.stat().st_size > MAX_READ_BYTES:
                continue

            try:
                text = file.read_text(
                    encoding="utf-8"
                )
            except (
                UnicodeDecodeError,
                OSError,
            ):
                continue

            for line_number, line in enumerate(
                text.splitlines(),
                start=1,
            ):
                if query.lower() in line.lower():
                    matches.append(
                        f"{self._relative(file)}:"
                        f"{line_number}: {line.strip()}"
                    )

                    if len(matches) >= max_results:
                        return "\n".join(matches)

        return "\n".join(matches)

    def _git(
        self,
        *args: str,
    ) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RepoToolError(
                result.stderr.strip()
                or result.stdout.strip()
                or "Git command failed."
            )

        return result.stdout

    def git_status(self) -> str:
        return self._git(
            "status",
            "--short",
        )

    def git_diff(self) -> str:
        return self._git(
            "diff",
            "--",
        )
