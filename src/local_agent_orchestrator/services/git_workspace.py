from __future__ import annotations

import re
import subprocess
from pathlib import Path


class GitWorkspaceError(RuntimeError):
    pass


class GitWorkspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._baseline_verified_clean = False

    def _run(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=check,
            )
        except subprocess.CalledProcessError as exc:
            joined_args = " ".join(args)

            raise GitWorkspaceError(
                exc.stderr.strip()
                or exc.stdout.strip()
                or f"git command failed: {joined_args}"
            ) from exc

    def assert_repository(self) -> None:
        result = self._run(
            "rev-parse",
            "--is-inside-work-tree",
            check=False,
        )

        if result.returncode != 0 or result.stdout.strip() != "true":
            raise GitWorkspaceError(
                f"Not a Git repository: {self.root}"
            )

    def status(self) -> list[str]:
        self.assert_repository()

        result = self._run(
            "status",
            "--porcelain",
        )

        return [
            line
            for line in result.stdout.splitlines()
            if line.strip()
        ]

    def assert_clean(self) -> None:
        dirty = self.status()

        if dirty:
            raise GitWorkspaceError(
                "Workspace has pre-existing changes. "
                "Commit or stash them before agent execution.\n"
                + "\n".join(dirty)
            )

        self._baseline_verified_clean = True

    def current_branch(self) -> str:
        self.assert_repository()

        result = self._run(
            "branch",
            "--show-current",
        )

        branch = result.stdout.strip()

        if not branch:
            raise GitWorkspaceError(
                "Repository is in detached HEAD state."
            )

        return branch

    def branch_exists(self, branch: str) -> bool:
        result = self._run(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        )

        return result.returncode == 0

    def create_agent_branch(
        self,
        run_id: str,
    ) -> str:
        if not self._baseline_verified_clean:
            raise GitWorkspaceError(
                "Clean baseline was not verified before branch creation."
            )

        current = self.current_branch()

        if current.startswith("agent/"):
            return current

        safe_run_id = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            run_id,
        ).strip("-")

        if not safe_run_id:
            raise GitWorkspaceError(
                "Run ID cannot produce a valid branch name."
            )

        branch = f"agent/{safe_run_id}"

        if self.branch_exists(branch):
            raise GitWorkspaceError(
                f"Agent branch already exists: {branch}"
            )

        self._run(
            "switch",
            "-c",
            branch,
        )

        return branch

    def switch_branch(self, branch: str) -> str:
        if not self._baseline_verified_clean:
            raise GitWorkspaceError(
                "Clean baseline was not verified before branch switch."
            )

        if not self.branch_exists(branch):
            raise GitWorkspaceError(
                f"Branch does not exist: {branch}"
            )

        current = self.current_branch()

        if current != branch:
            self._run(
                "switch",
                branch,
            )

        return self.current_branch()

    def checkpoint(self, message: str) -> str:
        if not self._baseline_verified_clean:
            raise GitWorkspaceError(
                "Clean baseline was not verified before execution."
            )

        self._run("add", "-A")

        staged = self._run(
            "diff",
            "--cached",
            "--quiet",
            check=False,
        )

        if staged.returncode == 0:
            return self.head()

        commit_args = ["commit", "-m", message]

        for key, fallback in (
            ("user.name", "local-agent-orchestrator"),
            ("user.email", "local-agent-orchestrator@localhost"),
        ):
            configured = self._run(
                "config",
                "--local",
                "--get",
                key,
                check=False,
            )

            if configured.returncode not in (0, 1):
                raise GitWorkspaceError(
                    configured.stderr.strip()
                    or f"git config lookup failed for {key}"
                )

            if configured.returncode != 0 or not configured.stdout.strip():
                commit_args[0:0] = ["-c", f"{key}={fallback}"]

        self._run(*commit_args)

        return self.head()

    def rollback(self) -> None:
        if not self._baseline_verified_clean:
            raise GitWorkspaceError(
                "Refusing rollback because clean baseline "
                "was not verified."
            )

        self._run(
            "reset",
            "--hard",
            "HEAD",
        )

        self._run(
            "clean",
            "-fd",
        )

    def head(self) -> str:
        return self._run(
            "rev-parse",
            "HEAD",
        ).stdout.strip()
