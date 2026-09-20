from __future__ import annotations

import argparse
import shlex

from local_agent_orchestrator.services.plan_loader import load_plan
from local_agent_orchestrator.services.plan_runner import run_execution_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent-plan"
    )

    parser.add_argument(
        "--workspace",
        required=True,
    )

    parser.add_argument(
        "--plan",
        required=True,
    )

    parser.add_argument(
        "--test-command",
        required=True,
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

    try:
        plan = load_plan(args.plan)
    except Exception as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")

    test_command = shlex.split(
        args.test_command
    )

    if not test_command:
        parser.error("--test-command cannot be empty")

    try:
        result = run_execution_plan(
            plan=plan,
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
    print(
        f"Tasks: {result.completed_tasks}/{result.total_tasks}"
    )
    print(f"Commits: {len(result.commits)}")
    print(f"Run dir: {result.run_dir}")
    print(f"Analytics: {result.analytics_path}")
    print(
        f"Retrospective: {result.retrospective_path}"
    )

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
