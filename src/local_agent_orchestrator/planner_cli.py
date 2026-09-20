from __future__ import annotations

import argparse
import shlex

from local_agent_orchestrator.services.planner_pipeline import (
    run_planned_request,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent-auto"
    )

    parser.add_argument(
        "--workspace",
        required=True,
    )

    parser.add_argument(
        "--request",
        required=True,
    )

    parser.add_argument(
        "--test-command",
        required=True,
    )

    parser.add_argument(
        "--planner-model",
        default="gpt-5.6-sol",
    )

    parser.add_argument(
        "--plans-dir",
        default=".agent/plans",
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
        result = run_planned_request(
            request=args.request,
            workspace_root=args.workspace,
            test_command=test_command,
            plans_dir=args.plans_dir,
            runs_dir=args.runs_dir,
            analytics_dir=args.analytics_dir,
            planner_model=args.planner_model,
        )
    except Exception as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")

    print(f"Plan: {result.plan_path}")
    print(f"Run: {result.run.run_id}")
    print(
        "Status:",
        "PASSED" if result.run.passed else "FAILED",
    )
    print(
        f"Tasks: {result.run.completed_tasks}/"
        f"{result.run.total_tasks}"
    )
    print(f"Commits: {len(result.run.commits)}")
    print(
        f"Retrospective: {result.run.retrospective_path}"
    )

    return 0 if result.run.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
