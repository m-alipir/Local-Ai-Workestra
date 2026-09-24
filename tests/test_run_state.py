import pytest

from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.run_state import (
    ExecutionLeaseError,
    RunStateManager,
)


def test_create_and_load_run(tmp_path):
    manager = RunStateManager(tmp_path)

    state = manager.create_run("Build a test feature")

    loaded = manager.load(state.run_id)

    assert loaded.request == "Build a test feature"
    assert loaded.status == TaskStatus.PENDING

    run_dir = manager.get_run_dir(state.run_id)
    assert (run_dir / "request.md").exists()
    assert (run_dir / "state.json").exists()


def test_execution_lease_rejects_a_second_run_until_released(tmp_path):
    manager = RunStateManager(tmp_path / "runs")
    lease = manager.acquire_execution_lease("run-one")
    try:
        with pytest.raises(ExecutionLeaseError, match="run-one"):
            manager.acquire_execution_lease("run-two")
    finally:
        manager.release_execution_lease(lease)

    manager.acquire_execution_lease("run-two").release()


def test_task_lifecycle(tmp_path):
    manager = RunStateManager(tmp_path)
    state = manager.create_run("Test request")

    task = manager.add_task(state, "Implement feature")

    manager.update_task(
        state,
        task.id,
        TaskStatus.RUNNING,
    )

    assert task.attempts == 1
    assert state.status == TaskStatus.RUNNING

    manager.update_task(
        state,
        task.id,
        TaskStatus.PASSED,
    )

    loaded = manager.load(state.run_id)

    assert loaded.tasks[0].status == TaskStatus.PASSED
    assert loaded.status == TaskStatus.PASSED
    assert loaded.current_task is None


def test_failed_task(tmp_path):
    manager = RunStateManager(tmp_path)
    state = manager.create_run("Test failure")

    task = manager.add_task(state, "Broken task")

    manager.update_task(
        state,
        task.id,
        TaskStatus.RUNNING,
    )

    manager.update_task(
        state,
        task.id,
        TaskStatus.FAILED,
        error="tests failed",
    )

    loaded = manager.load(state.run_id)

    assert loaded.status == TaskStatus.FAILED
    assert loaded.tasks[0].error == "tests failed"
