from datetime import datetime, timezone

from local_agent_orchestrator.models.metrics import TaskMetrics
from local_agent_orchestrator.services.metrics import write_task_metrics


def test_write_task_metrics(tmp_path):
    metrics = TaskMetrics(
        task_id="task-001",
        description="Implement feature",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        duration_sec=1.25,
        attempts=2,
        passed=True,
        changed_files=["app.py"],
        test_returncode=0,
        commit="abc123",
        diagnoses=["Root cause found"],
    )

    path = write_task_metrics(
        tmp_path,
        metrics,
    )

    assert path.exists()

    text = path.read_text()

    assert '"task_id": "task-001"' in text
    assert '"attempts": 2' in text
    assert '"commit": "abc123"' in text
    assert "Root cause found" in text
