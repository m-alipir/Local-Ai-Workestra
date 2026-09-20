import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.models.config import ModelConfig, ModelsConfig
from local_agent_orchestrator.models.security import SecurityReview

from .cases import CASES
from .runner import (
    BONSAI_MODEL_NAME,
    _selected_models,
    _workspace,
    classify_findings,
    run_benchmark,
)


def test_cases_cover_security_categories_and_clean_control():
    names = {category for case in CASES for category in case.expected}

    assert {"command_injection", "path_traversal", "secret_exposure"} <= names
    assert any(not case.expected for case in CASES)
    assert len(CASES) == 5


def test_each_case_is_a_committed_git_diff(tmp_path: Path):
    for case in CASES:
        root = _workspace(case, tmp_path)
        diff = subprocess.run(
            ["git", "diff", "--no-ext-diff", "HEAD^", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert f"b/{case.path}" in diff
        committed = subprocess.run(
            ["git", "show", f"HEAD:{case.path}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert committed == case.changed


def test_classifier_reports_expected_and_false_positive_categories():
    review = SecurityReview.model_validate(
        {
            "findings": [
                {
                    "severity": "high",
                    "title": "Command injection",
                    "description": "User input reaches shell=True.",
                    "recommendation": "Avoid shell execution.",
                },
                {
                    "severity": "low",
                    "title": "Unrelated style issue",
                    "description": "This is not a security issue.",
                    "recommendation": "Rename the helper.",
                },
            ]
        }
    )

    assert classify_findings(review) == {"command_injection", "unclassified"}


def test_benchmark_uses_existing_security_review_interface():
    configured = ModelsConfig(
        models={
            name: ModelConfig(role=name, hf=f"test/{name}")
            for name in (
                "qwen_coder",
                "gpt_oss",
                "qwen_general",
                "devstral",
                "nemotron",
            )
        }
    )
    fake_review = SecurityReview.model_validate(
        {
            "findings": [
                {
                    "severity": "high",
                    "title": "Command injection",
                    "description": "shell=True permits arbitrary command execution",
                    "recommendation": "Use argument arrays.",
                }
            ]
        }
    )
    fake_call = MagicMock(return_value=fake_review)

    with (
        patch(
            "local_agent_orchestrator.services.security.load_models",
            return_value=configured,
        ),
        patch(
            "local_agent_orchestrator.services.security.run_security_review",
            fake_call,
        ),
    ):
        results = run_benchmark(
            models=["qwen_general"],
            cases=["command_injection"],
        )

    assert results[0].detected == ("command_injection",)
    assert results[0].missed == ()
    assert results[0].false_positives == ()
    fake_call.assert_called_once()
    assert fake_call.call_args.kwargs["revision"] == "HEAD"
    assert fake_call.call_args.kwargs["changed_files"] == ["reporting.py"]


def test_benchmark_records_clean_control_false_positive():
    configured = ModelsConfig(
        models={
            name: ModelConfig(role=name, hf=f"test/{name}")
            for name in (
                "qwen_coder",
                "gpt_oss",
                "qwen_general",
                "devstral",
                "nemotron",
            )
        }
    )
    fake_review = SecurityReview.model_validate(
        {
            "findings": [
                {
                    "severity": "low",
                    "title": "Exposed API token",
                    "description": "A token appears in the change.",
                    "recommendation": "Remove the token.",
                }
            ]
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.security.load_models",
            return_value=configured,
        ),
        patch(
            "local_agent_orchestrator.services.security.run_security_review",
            return_value=fake_review,
        ),
    ):
        result = run_benchmark(
            models=["qwen_general"],
            cases=["clean_control"],
        )[0]

    assert result.expected == ()
    assert result.detected == ("secret_exposure",)
    assert result.false_positives == ("secret_exposure",)
    assert result.missed == ()
    assert result.latency_ms >= 0


def test_bonsai_is_benchmark_only_model_alias():
    configured = ModelsConfig(
        models={
            name: ModelConfig(role=name, hf=f"test/{name}")
            for name in (
                "qwen_coder",
                "gpt_oss",
                "qwen_general",
                "devstral",
                "nemotron",
            )
        }
    )

    with patch(
        "local_agent_orchestrator.services.security.load_models",
        return_value=configured,
    ):
        assert _selected_models([BONSAI_MODEL_NAME]) is configured
