import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.models.config import ModelConfig, ModelsConfig

from .runner import evaluate_output, run_benchmark


def _context() -> dict:
    return {
        "authoritative_facts": {
            "run_status": "passed",
            "tasks": [{
                "task_id": "task-001",
                "task_status": "passed",
                "accepted_model": "qwen_coder",
                "accepted_attempt": 1,
                "commit": "b89066d5345eab7c26d45c90b6e777b3c9e5b543",
                "baseline": {
                    "failure_identities": ["tests/test_admin.py::test_scheduler"],
                },
                "verification_classification": "preexisting_failures_only",
            }],
        },
    }


def test_evaluator_accepts_grounded_baseline_aware_output():
    output = """STRONG:
Task passed on the first attempt.
WEAK:
The scheduler failure is pre-existing baseline debt.
WASTE:
None recorded.
RECOMMENDATION:
No corrective action for this task; do not investigate the unrelated baseline failure.
REASONING_ADJUSTMENT:
No change.
"""

    result = evaluate_output(output, _context())

    assert result["malformed_output"] is False
    assert result["factual_grounding"] == "grounded"
    assert result["unsupported_claims"] == ()
    assert result["root_cause_analysis"].startswith("evidence-aligned")


def test_evaluator_flags_baseline_hallucination_and_unsupported_routing():
    output = """STRONG:
The edit introduced the scheduler regression.
WEAK:
No model reasoning caused the issue.
WASTE:
Debugging the failure consumed the task.
RECOMMENDATION:
Investigate the scheduler failure and route future tasks to Devstral.
REASONING_ADJUSTMENT:
Use a stronger model.
"""

    result = evaluate_output(output, _context())

    assert result["malformed_output"] is False
    assert result["factual_grounding"] == "contradictory_or_unsupported"
    assert "attributes baseline failure to agent" in result["unsupported_claims"]
    assert "unsupported model-routing recommendation" in result["unsupported_claims"]
    assert result["root_cause_analysis"] == "unsupported attribution or diagnosis"


def test_evaluator_marks_missing_sections_malformed():
    result = evaluate_output("The task passed.", _context())

    assert result["malformed_output"] is True
    assert result["malformed_reason"] == "expected exactly five ordered sections"


def test_models_receive_identical_authoritative_context(tmp_path: Path):
    run_dir = tmp_path / "run"
    (run_dir / "metrics").mkdir(parents=True)
    (run_dir / "metrics" / "task-001.json").write_text(json.dumps({
        "task_id": "task-001",
        "passed": True,
        "accepted_model": "qwen_coder",
        "accepted_attempt": 1,
        "commit": "abc123456789",
        "baseline_returncode": 0,
        "baseline_passed": True,
        "baseline_failure_identities": [],
        "post_change_failure_identities": [],
        "verification_classification": "passed",
        "operation_failures": [],
    }))
    (run_dir / "state.json").write_text(json.dumps({
        "status": "passed",
        "tasks": [{"id": "task-001", "status": "passed"}],
    }))
    (run_dir / "trajectory.jsonl").write_text("")
    configured = ModelsConfig(models={
        name: ModelConfig(role=name, hf=f"test/{name}")
        for name in ("nemotron", "qwen_general")
    })
    settings = MagicMock()
    settings.resources.minimum_free_ram_gb = 0
    settings.resources.minimum_free_vram_gb = 0
    settings.orchestrator.model_start_timeout = 1
    settings.orchestrator.model_stop_timeout = 1
    fake = MagicMock()
    fake.run.return_value.content = (
        "STRONG:\nPassed.\nWEAK:\nNone.\nWASTE:\nNone.\n"
        "RECOMMENDATION:\nNo change.\nREASONING_ADJUSTMENT:\nNo change."
    )

    with (
        patch("benchmarks.retrospective.runner.load_models", return_value=configured),
        patch("benchmarks.retrospective.runner.load_settings", return_value=settings),
        patch("benchmarks.retrospective.runner.NemotronRetrospective", return_value=fake),
    ):
        results = run_benchmark(run_dir, ["nemotron", "bonsai2"])

    assert len(results) == 2
    assert results[0].context_sha256 == results[1].context_sha256
    assert fake.run.call_count == 2
    assert fake.run.call_args_list[0].args == fake.run.call_args_list[1].args
