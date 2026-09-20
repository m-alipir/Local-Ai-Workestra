import json

from local_agent_orchestrator.services.plan_loader import load_plan


def test_load_plan(tmp_path):
    path = tmp_path / "plan.json"

    path.write_text(
        json.dumps({
            "request": "Build feature",
            "tasks": [
                {"description": "Task one"},
                {"description": "Task two"},
            ],
        })
    )

    plan = load_plan(path)

    assert plan.request == "Build feature"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].description == "Task one"
