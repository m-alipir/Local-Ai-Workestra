from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest.mock import patch

from local_agent_orchestrator.agents import nemotron_retrospective as retrospective_agent
from local_agent_orchestrator.agents.nemotron_retrospective import (
    NemotronRetrospective,
)
from local_agent_orchestrator.core.config import load_models, load_settings
from local_agent_orchestrator.models.config import ModelConfig
from local_agent_orchestrator.services.retrospective import (
    build_retrospective_context,
)


BONSAI_MODEL_NAME = "bonsai2"
BONSAI_BINARY = Path("~/llama.cpp-bonsai-rocm/build/bin/llama-server").expanduser()
BONSAI_MODEL = Path(
    "~/Bonsai-demo/models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PQ2_0.gguf"
).expanduser()
LEGACY_NEMOTRON = ModelConfig(
    role="legacy_retrospective_benchmark",
    hf="bartowski/nvidia_NVIDIA-Nemotron-Nano-12B-v2-GGUF:Q6_K",
    reasoning="low",
)
SECTION_NAMES = ("STRONG", "WEAK", "WASTE", "RECOMMENDATION", "REASONING_ADJUSTMENT")


@dataclass(frozen=True, slots=True)
class RetrospectiveBenchmarkResult:
    model: str
    run_dir: str
    context_sha256: str
    context_chars: int
    latency_ms: float
    malformed_output: bool
    malformed_reason: str | None
    factual_grounding: str
    grounded_fact_count: int
    grounded_facts: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    root_cause_analysis: str
    supported_suggestions: tuple[str, ...]
    unsupported_suggestions: tuple[str, ...]
    output: str
    error: str | None = None


def _parse_sections(content: str) -> tuple[dict[str, str], str | None]:
    matches = list(
        re.finditer(
            r"(?m)^\s*(STRONG|WEAK|WASTE|RECOMMENDATION|REASONING_ADJUSTMENT)\s*:\s*$",
            content,
        )
    )
    names = [match.group(1) for match in matches]
    if names != list(SECTION_NAMES):
        return {}, "expected exactly five ordered sections"

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        value = content[match.end():end].strip()
        if not value:
            return {}, f"empty section: {match.group(1)}"
        sections[match.group(1)] = value
    return sections, None


def _positive_action(text: str, action: str, target: str) -> bool:
    for match in re.finditer(
        rf"\b{action}\b.{{0,100}}\b{target}\b",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        prefix = text[max(0, match.start() - 20):match.start()].lower()
        if "not" not in prefix[-12:] and "don't" not in prefix[-12:]:
            return True
    return False


def evaluate_output(content: str, context: dict) -> dict[str, object]:
    sections, malformed_reason = _parse_sections(content)
    text = content.lower()
    task = context.get("authoritative_facts", {}).get("tasks", [{}])[0]
    classification = task.get("verification_classification")
    baseline_failure = (
        (task.get("baseline") or {}).get("failure_identities") or ["unknown"]
    )[0]

    grounded: list[str] = []
    if task.get("task_status") == "passed" and re.search(
        r"\b(task|change|run)\b.{0,50}\b(passed|completed|success)", text, re.DOTALL
    ):
        grounded.append("task passed")
    if classification == "preexisting_failures_only" and (
        "pre-existing" in text or "baseline" in text
    ) and ("scheduler" in text or "test_admin" in text or baseline_failure in text):
        grounded.append("baseline failure is pre-existing")
    if task.get("accepted_model") and task.get("accepted_model", "").lower() in text:
        grounded.append("accepted model")
    if task.get("accepted_attempt") == 1 and re.search(
        r"\b(attempt|retry)\b.{0,20}\b1\b|first(?:\s+\w+){0,2}\s+attempt|no retries",
        text,
    ):
        grounded.append("accepted attempt 1")
    checkpoint_events = task.get("checkpoint_events") or []
    if checkpoint_events and "checkpoint" in text and re.search(
        r"\b(passed|created|successful|success)\b", text
    ):
        grounded.append("checkpoint passed")
    changed_files = task.get("changed_files") or []
    if changed_files and all(str(path).lower() in text for path in changed_files):
        grounded.append("changed files")
    if task.get("commit") and task["commit"][:12].lower() in text:
        grounded.append("checkpoint commit")

    unsupported: list[str] = []
    if classification == "preexisting_failures_only":
        if re.search(
            r"\b(agent|change|edit|task)\b.{0,40}\b(introduced|caused|created|triggered)\b.{0,80}\b(failure|scheduler|test_admin)",
            text,
            re.DOTALL,
        ):
            unsupported.append("attributes baseline failure to agent")
        separate_debt = any(
            phrase in text
            for phrase in (
                "dedicated task",
                "separate task",
                "track the remaining",
                "track ... separately",
                "unrelated pre-existing repository debt",
            )
        )
        if any(
            _positive_action(text, action, target)
            for action in ("investigate", "fix", "resolve", "debug", "repair", "address")
            for target in ("scheduler", "test_admin", "baseline failure")
        ) and not separate_debt:
            unsupported.append("recommends work on baseline-only failure")
    if "lack of model reasoning" in text or "no model reasoning" in text:
        unsupported.append("claims missing model reasoning")
    if "route" in text and any(name in text for name in ("devstral", "nemotron", "qwen")):
        unsupported.append("unsupported model-routing recommendation")
    if "optimization review" in text and any(
        action in text for action in ("missing", "should add", "needed", "recommend")
    ):
        unsupported.append("unsupported optimization recommendation")

    supported_suggestions: list[str] = []
    if sections:
        recommendation = sections["RECOMMENDATION"].lower()
        if any(
            phrase in recommendation
            for phrase in ("no corrective action", "no change", "do not attribute", "unrelated")
        ):
            supported_suggestions.append("baseline-aware/no corrective action")
        elif classification == "preexisting_failures_only" and any(
            phrase in text
            for phrase in (
                "dedicated task",
                "separate task",
                "track the remaining",
                "track ... separately",
            )
        ):
            supported_suggestions.append("separate tracking of baseline debt")
    unsupported_suggestions = [
        item for item in unsupported
        if "recommends" in item or "recommendation" in item
    ]

    if unsupported:
        grounding = "contradictory_or_unsupported"
    elif len(grounded) >= 2:
        grounding = "grounded"
    elif grounded:
        grounding = "partially_grounded"
    else:
        grounding = "ungrounded"

    if classification == "preexisting_failures_only" and "baseline failure is pre-existing" in grounded:
        root_cause = "evidence-aligned attribution; concrete underlying cause remains unknown"
    elif any("baseline failure" in item for item in unsupported):
        root_cause = "unsupported attribution or diagnosis"
    else:
        root_cause = "unknown"

    return {
        "malformed_output": malformed_reason is not None,
        "malformed_reason": malformed_reason,
        "factual_grounding": grounding,
        "grounded_fact_count": len(grounded),
        "grounded_facts": tuple(grounded),
        "unsupported_claims": tuple(unsupported),
        "root_cause_analysis": root_cause,
        "supported_suggestions": tuple(supported_suggestions),
        "unsupported_suggestions": tuple(unsupported_suggestions),
    }


def _model_for(model_name: str, configured):
    if model_name == BONSAI_MODEL_NAME:
        return configured.models.get(
            BONSAI_MODEL_NAME,
            ModelConfig(
                role="benchmark_bonsai",
                hf="bonsai2",
                reasoning="high",
            ),
        )
    if model_name == "nemotron":
        return configured.models.get("nemotron", LEGACY_NEMOTRON)
    return configured.models[model_name]


def _run_one(
    model_name: str,
    run_dir: Path,
    context: dict,
    context_json: str,
    configured,
    settings,
) -> RetrospectiveBenchmarkResult:
    started = time.perf_counter()
    model = _model_for(model_name, configured)
    output = ""
    error: str | None = None
    server_patch = nullcontext()
    if model_name == BONSAI_MODEL_NAME:
        original_server = retrospective_agent.LlamaServer

        def bonsai_server(**kwargs):
            kwargs.setdefault("binary", BONSAI_BINARY)
            kwargs.setdefault("model_path", BONSAI_MODEL)
            kwargs.setdefault("flash_attention", True)
            return original_server(
                **kwargs,
            )

        server_patch = patch.object(
            retrospective_agent,
            "LlamaServer",
            bonsai_server,
        )

    try:
        reviewer = NemotronRetrospective(
            model=model,
            minimum_free_ram_gb=settings.resources.minimum_free_ram_gb,
            minimum_free_vram_gb=settings.resources.minimum_free_vram_gb,
            start_timeout=settings.orchestrator.model_start_timeout,
            stop_timeout=settings.orchestrator.model_stop_timeout,
        )
        with server_patch:
            output = reviewer.run(context_json).content
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    evaluation = evaluate_output(output, context) if not error else {
        "malformed_output": True,
        "malformed_reason": "model call failed",
        "factual_grounding": "unknown",
        "grounded_fact_count": 0,
        "grounded_facts": (),
        "unsupported_claims": (),
        "root_cause_analysis": "unknown",
        "supported_suggestions": (),
        "unsupported_suggestions": (),
    }
    return RetrospectiveBenchmarkResult(
        model=model_name,
        run_dir=str(run_dir),
        context_sha256=hashlib.sha256(context_json.encode()).hexdigest(),
        context_chars=len(context_json),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        output=output,
        error=error,
        **evaluation,
    )


def run_benchmark(
    run_dir: str | Path,
    models: list[str] = ("nemotron", BONSAI_MODEL_NAME),
) -> list[RetrospectiveBenchmarkResult]:
    root = Path(run_dir)
    context = build_retrospective_context(root)
    context_json = json.dumps(context, indent=2, ensure_ascii=False, sort_keys=True)
    configured = load_models()
    settings = load_settings()
    missing = sorted(
        set(models) - configured.models.keys() - {BONSAI_MODEL_NAME, "nemotron"}
    )
    if missing:
        raise ValueError("Unknown retrospective model(s): " + ", ".join(missing))
    return [
        _run_one(model, root, context, context_json, configured, settings)
        for model in models
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare retrospective models on identical stored run evidence."
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path("runs-ai-assistant/7120a13568ea"),
    )
    parser.add_argument(
        "--models",
        default="nemotron,bonsai2",
        help="Comma-separated models; bonsai2 is benchmark-only.",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        results = run_benchmark(
            args.run_dir,
            [name.strip() for name in args.models.split(",") if name.strip()],
        )
    except (KeyError, ValueError, OSError) as exc:
        _parser().error(str(exc))

    rendered = json.dumps(
        [asdict(result) for result in results],
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if all(result.error is None for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
