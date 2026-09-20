from __future__ import annotations

import json
from pathlib import Path


def append_run_analytics(
    run_id: str,
    metrics: list[dict],
    analytics_dir: str | Path = ".agent/analytics",
) -> Path:
    root = Path(analytics_dir)
    root.mkdir(parents=True, exist_ok=True)

    path = root / f"{run_id}.json"

    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "tasks": metrics,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return path
