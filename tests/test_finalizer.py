import json
from unittest.mock import patch

from local_agent_orchestrator.services.finalizer import finalize_run


def test_finalize_run(tmp_path):
    run_dir = tmp_path / "run"
    metrics_dir = run_dir / "metrics"
    metrics_dir.mkdir(parents=True)

    (metrics_dir / "task-001.json").write_text(
        json.dumps({
            "task_id": "task-001",
            "attempts": 1,
            "passed": True,
        })
    )

    retrospective = run_dir / "retrospective.md"

    with patch(
        "local_agent_orchestrator.services.finalizer.generate_retrospective",
        return_value=retrospective,
    ) as retro:
        result = finalize_run(
            run_id="run123",
            run_dir=run_dir,
            analytics_dir=tmp_path / "analytics",
        )

    assert result.task_count == 1
    assert result.analytics_path.exists()
    assert result.retrospective_path == retrospective
    retro.assert_called_once_with(run_dir=run_dir)
