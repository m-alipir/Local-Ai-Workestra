from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from local_agent_orchestrator.services.analytics import append_run_analytics
from local_agent_orchestrator.services.retrospective import (
    collect_run_metrics,
    generate_retrospective,
)


@dataclass(slots=True)
class FinalizationResult:
    analytics_path: Path
    retrospective_path: Path
    task_count: int


def finalize_run(
    run_id: str,
    run_dir: str | Path,
    analytics_dir: str | Path = ".agent/analytics",
) -> FinalizationResult:
    metrics = collect_run_metrics(run_dir)

    analytics_path = append_run_analytics(
        run_id=run_id,
        metrics=metrics,
        analytics_dir=analytics_dir,
    )

    retrospective_path = generate_retrospective(
        run_dir=run_dir,
    )

    return FinalizationResult(
        analytics_path=analytics_path,
        retrospective_path=retrospective_path,
        task_count=len(metrics),
    )
