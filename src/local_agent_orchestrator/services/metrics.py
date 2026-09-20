from __future__ import annotations

import json
from pathlib import Path

from local_agent_orchestrator.models.metrics import TaskMetrics


def write_task_metrics(
    run_dir: str | Path,
    metrics: TaskMetrics,
) -> Path:
    root = Path(run_dir)
    metrics_dir = root / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    path = metrics_dir / f"{metrics.task_id}.json"

    path.write_text(
        json.dumps(
            metrics.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return path
