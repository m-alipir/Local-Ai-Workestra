from __future__ import annotations

import argparse
import shlex

from local_agent_orchestrator.services.resume import (
    approve_waiting_task,
    resume_execution_plan,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent-control"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    approve = subparsers.add_parser(
        "approve",
        help="Approve the task currently waiting for human approval.",
    )

    approve.add_argument(
        "run_id",
    )

    approve.add_argument(
        "--task-id",
        default=None,
    )

    approve.add_argument(
        "--runs-dir",
        default="runs",
    )

    resume = subparsers.add_parser(
        "resume",
        help="Resume a previously paused execution plan.",
    )

    resume.add_argument(
        "run_id",
    )

    resume.add_argument(
        "--workspace",
        required=True,
    )

    resume.add_argument(
        "--test-command",
        required=True,
    )

    resume.add_argument(
        "--runs-dir",
        default="runs",
    )

    resume.add_argument(
        "--analytics-dir",
        default=".agent/analytics",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "approve":
        try:
            task_id = approve_waiting_task(
                run_id=args.run_id,
                runs_dir=args.runs_dir,
                task_id=args.task_id,
            )
        except Exception as exc:
            parser.exit(1, f"{parser.prog}: error: {exc}\n")

        print(f"Approved: {task_id}")
        print(f"Run: {args.run_id}")

        return 0

    if args.command == "resume":
        test_command = shlex.split(
            args.test_command
        )

        if not test_command:
            parser.error(
                "--test-command cannot be empty"
            )

        try:
            result = resume_execution_plan(
                run_id=args.run_id,
                workspace_root=args.workspace,
                test_command=test_command,
                runs_dir=args.runs_dir,
                analytics_dir=args.analytics_dir,
            )
        except Exception as exc:
            parser.exit(1, f"{parser.prog}: error: {exc}\n")

        print(f"Run: {result.run_id}")

        if result.waiting_for_approval:
            print("Status: WAITING_FOR_APPROVAL")
            print(
                f"Task: {result.waiting_task_id}"
            )
            return 2

        print(
            "Status:",
            "PASSED" if result.passed else "FAILED",
        )

        print(
            f"Tasks: {result.completed_tasks}/"
            f"{result.total_tasks}"
        )

        print(
            f"Commits: {len(result.commits)}"
        )

        return 0 if result.passed else 1

    parser.error(
        f"Unknown command: {args.command}"
    )

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
