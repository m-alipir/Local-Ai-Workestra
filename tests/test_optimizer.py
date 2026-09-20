from unittest.mock import MagicMock, patch

from local_agent_orchestrator.services.optimizer import (
    requires_optimization_review,
    run_optimization_review,
)


def test_optimizer_trigger():
    assert requires_optimization_review(
        "Optimize database query latency",
        ["db.py"],
    ) is True


def test_optimizer_ignores_simple_task():
    assert requires_optimization_review(
        "Rename variable",
        ["app.py"],
    ) is False


def test_run_optimization_review(tmp_path):
    (tmp_path / "db.py").write_text("def query(): pass\n")

    fake = MagicMock()
    fake.review.return_value.content = "Measure query count before optimizing."

    with patch(
        "local_agent_orchestrator.services.optimizer.OptimizerAgent",
        return_value=fake,
    ):
        result = run_optimization_review(
            task="Optimize database query latency",
            changed_files=["db.py"],
            workspace_root=tmp_path,
        )

    assert "Measure query count" in result
