from unittest.mock import patch

from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.task_executor import TaskExecutionResult
from local_agent_orchestrator.services.test_runner import CommandResult
from local_agent_orchestrator.services.tracked_executor import (
    execute_tracked_task,
)


def make_result(passed: bool, attempts: int) -> TaskExecutionResult:
    return TaskExecutionResult(
        passed=passed,
        attempts=attempts,
        changed_files=["app.py"],
        diagnoses=[],
        test_result=CommandResult(
            passed=passed,
            returncode=0 if passed else 1,
            stdout="passed" if passed else "failed",
            stderr="" if passed else "assertion error",
        ),
    )


def test_tracked_task_passes(tmp_path):
    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Build feature")
    task = manager.add_task(state, "Implement feature")

    with patch(
        "local_agent_orchestrator.services.tracked_executor.execute_task_with_retries",
        return_value=make_result(True, 2),
    ):
        execute_tracked_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
        )

    loaded = manager.load(state.run_id)

    assert loaded.status == TaskStatus.PASSED
    assert loaded.tasks[0].status == TaskStatus.PASSED
    assert loaded.tasks[0].attempts == 2


def test_tracked_task_fails(tmp_path):
    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Build feature")
    task = manager.add_task(state, "Implement feature")

    with patch(
        "local_agent_orchestrator.services.tracked_executor.execute_task_with_retries",
        return_value=make_result(False, 3),
    ):
        execute_tracked_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
        )

    loaded = manager.load(state.run_id)

    assert loaded.status == TaskStatus.FAILED
    assert loaded.tasks[0].status == TaskStatus.FAILED
    assert loaded.tasks[0].attempts == 3
    assert loaded.tasks[0].error == "STDOUT:\nfailed\n\nSTDERR:\nassertion error"


def test_tracked_executor_writes_trajectory(tmp_path):
    import json
    from unittest.mock import patch

    from local_agent_orchestrator.models.task import RunState
    from local_agent_orchestrator.services.run_state import RunStateManager
    from local_agent_orchestrator.services.task_executor import (
        TaskExecutionResult,
    )
    from local_agent_orchestrator.services.test_runner import (
        CommandResult,
    )

    runs = tmp_path / "runs"
    manager = RunStateManager(runs)
    state = manager.create_run("Trajectory test")
    task = manager.add_task(state, "Implement feature")

    result = TaskExecutionResult(
        passed=True,
        attempts=1,
        changed_files=["app.py"],
        test_result=CommandResult(
            passed=True,
            returncode=0,
            stdout="ok",
            stderr="",
        ),
        diagnoses=[],
        qwen_attempts=1,
        devstral_used=False,
    )

    def fake_execute(**kwargs):
        callback = kwargs["event_callback"]

        callback({
            "event": "model_attempt_started",
            "model": "qwen_coder",
            "attempt": 1,
        })

        callback({
            "event": "edit_operations_requested",
            "model": "qwen_coder",
            "attempt": 1,
            "operations": [{
                "kind": "create_file",
                "path": "app.py",
                "content": "value = 1\n",
            }],
        })

        callback({
            "event": "tests_finished",
            "model": "qwen_coder",
            "attempt": 1,
            "passed": True,
        })

        return result

    with patch(
        "local_agent_orchestrator.services.tracked_executor.execute_task_with_retries",
        side_effect=fake_execute,
    ):
        execute_tracked_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
        )

    trajectory = (
        manager.get_run_dir(state.run_id)
        / "trajectory.jsonl"
    )

    assert trajectory.exists()

    events = [
        json.loads(line)
        for line in trajectory.read_text().splitlines()
    ]

    assert [
        event["event"]
        for event in events
    ] == [
        "task_started",
        "model_attempt_started",
        "edit_operations_requested",
        "tests_finished",
        "task_completed",
    ]

    assert events[1]["model"] == "qwen_coder"
    assert events[2]["operations"][0]["path"] == "app.py"
    assert events[3]["passed"] is True
