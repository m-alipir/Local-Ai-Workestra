from __future__ import annotations

import json
from pathlib import Path

from local_agent_orchestrator.models.trajectory import TrajectoryEvent


def append_trajectory_event(
    run_dir: str | Path,
    event: TrajectoryEvent,
) -> Path:
    path = Path(run_dir) / "trajectory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(
                event.model_dump(mode="json"),
                ensure_ascii=False,
            )
            + "\n"
        )

    return path
