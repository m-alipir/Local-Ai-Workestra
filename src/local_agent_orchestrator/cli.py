from __future__ import annotations

import argparse
import shlex

from local_agent_orchestrator.services.orchestrator import run_single_task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent"
    )

    parser.add_argument(
        "--workspace",
        required=True,
        help="Target Git repository",
    )

    parser.add_argument(
        "--task",
        required=True,
        help="Task for the coding agent",
    )

    parser.add_argument(
        "--test-command",
        required=True,
        help="Command used to validate the implementation",
    )

    parser.add_argument(
        "--runs-dir",
        default="runs",
    )

    parser.add_argument(
        "--analytics-dir",
        default=".agent/analytics",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    test_command = shlex.split(
        args.test_command
    )

    if not test_command:
        parser.error("--test-command cannot be empty")

    try:
        result = run_single_task(
            task=args.task,
            workspace_root=args.workspace,
            test_command=test_command,
            runs_dir=args.runs_dir,
            analytics_dir=args.analytics_dir,
        )
    except Exception as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")

    print(f"Run: {result.run_id}")
    print(
        "Status:",
        "PASSED" if result.passed else "FAILED",
    )
    print(f"Attempts: {result.attempts}")
    print(f"Commit: {result.commit or 'none'}")
    print(f"Run dir: {result.run_dir}")
    print(f"Metrics: {result.metrics_path}")
    print(f"Analytics: {result.analytics_path}")
    print(
        f"Retrospective: {result.retrospective_path}"
    )

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
