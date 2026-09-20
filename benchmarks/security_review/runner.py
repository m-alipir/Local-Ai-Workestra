from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest.mock import patch

from local_agent_orchestrator.agents import security_reviewer as security_agent
from local_agent_orchestrator.models.config import ModelConfig
from local_agent_orchestrator.models.security import SecurityReview
from local_agent_orchestrator.services import security as security_service

from .cases import CASES, CASE_BY_NAME, SecurityCase


CATEGORY_MARKERS = {
    "command_injection": (
        "command injection",
        "shell injection",
        "arbitrary command",
        "shell=true",
        "os.system",
        "subprocess",
    ),
    "path_traversal": (
        "path traversal",
        "directory traversal",
        "../",
        "outside the intended directory",
        "unsanitized path",
    ),
    "secret_exposure": (
        "secret",
        "credential",
        "api key",
        "api token",
        "access token",
        "sensitive token",
    ),
}

BONSAI_MODEL_NAME = "bonsai2"
BONSAI_BINARY = Path("~/llama.cpp-bonsai-rocm/build/bin/llama-server").expanduser()
BONSAI_MODEL = Path(
    "~/Bonsai-demo/models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PQ2_0.gguf"
).expanduser()
LEGACY_QWEN_GENERAL = ModelConfig(
    role="legacy_security_benchmark",
    hf="bartowski/Qwen_Qwen3-30B-A3B-GGUF:IQ4_XS",
    reasoning="medium_high",
)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    model: str
    case: str
    expected: tuple[str, ...]
    detected: tuple[str, ...]
    missed: tuple[str, ...]
    false_positives: tuple[str, ...]
    finding_titles: tuple[str, ...]
    latency_ms: float
    error: str | None = None


def classify_findings(review: SecurityReview) -> set[str]:
    detected: set[str] = set()

    for finding in review.findings:
        text = " ".join(
            (
                finding.title,
                finding.description,
                finding.recommendation,
            )
        ).lower()

        matched = False
        for category, markers in CATEGORY_MARKERS.items():
            if any(marker in text for marker in markers):
                detected.add(category)
                matched = True

        if not matched:
            detected.add("unclassified")

    return detected


def _git(command: list[str], root: Path) -> None:
    subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _workspace(case: SecurityCase, parent: Path) -> Path:
    root = parent / case.name
    root.mkdir()
    _git(["git", "init", "-q"], root)
    _git(["git", "config", "user.name", "Security Benchmark"], root)
    _git(["git", "config", "user.email", "benchmark@example.com"], root)

    path = root / case.path
    path.write_text(case.baseline, encoding="utf-8")
    _git(["git", "add", case.path], root)
    _git(["git", "commit", "-qm", "baseline"], root)

    path.write_text(case.changed, encoding="utf-8")
    _git(["git", "add", case.path], root)
    _git(["git", "commit", "-qm", case.name], root)
    return root


def _selected_models(names: list[str]):
    configured = security_service.load_models()
    missing = sorted(
        set(names)
        - configured.models.keys()
        - {BONSAI_MODEL_NAME, "qwen_general"}
    )
    if missing:
        raise ValueError(
            "Unknown configured model(s): " + ", ".join(missing)
        )
    return configured


def _run_one(model_name: str, case: SecurityCase, configured) -> BenchmarkResult:
    if model_name == "qwen_general":
        selected = LEGACY_QWEN_GENERAL
    elif model_name == BONSAI_MODEL_NAME:
        selected = configured.models.get(
            BONSAI_MODEL_NAME,
            ModelConfig(
                role="benchmark_bonsai",
                hf="bonsai2",
                reasoning="high",
            ),
        )
    else:
        selected = configured.models[model_name]
    if model_name == BONSAI_MODEL_NAME:
        selected = selected.model_copy(
            update={
                "hf": "bonsai2",
                # Bonsai's chat template accepts xhigh, while the shared
                # adapter maps the existing high level to xhigh.
                "reasoning": "high",
            }
        )
    remapped = configured.model_copy(
        update={
            "models": {
                **configured.models,
                # Security review now routes through the active GPT-OSS slot;
                # benchmark aliases are remapped only in this process.
                "gpt_oss": selected,
            }
        }
    )

    started = time.perf_counter()
    finding_titles: tuple[str, ...] = ()

    with tempfile.TemporaryDirectory(prefix="security-review-") as temp:
        root = _workspace(case, Path(temp))
        try:
            server_patch = nullcontext()
            if model_name == BONSAI_MODEL_NAME:
                original_server = security_agent.LlamaServer

                def bonsai_server(**kwargs):
                    return original_server(
                        binary=BONSAI_BINARY,
                        model_path=BONSAI_MODEL,
                        flash_attention=True,
                        **kwargs,
                    )

                server_patch = patch.object(
                    security_agent,
                    "LlamaServer",
                    bonsai_server,
                )

            with patch.object(
                security_service,
                "load_models",
                return_value=remapped,
            ), server_patch:
                review = security_service.run_security_review(
                    task=case.task,
                    changed_files=[case.path],
                    workspace_root=root,
                    revision="HEAD",
                )
            detected = classify_findings(review)
            finding_titles = tuple(finding.title for finding in review.findings)
            error = None
        except Exception as exc:
            detected = set()
            error = f"{type(exc).__name__}: {exc}"

    expected = set(case.expected)
    return BenchmarkResult(
        model=model_name,
        case=case.name,
        expected=tuple(sorted(expected)),
        detected=tuple(sorted(detected)),
        missed=tuple(sorted(expected - detected)),
        false_positives=tuple(sorted(detected - expected)),
        finding_titles=finding_titles,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        error=error,
    )


def run_benchmark(
    models: list[str],
    cases: list[str] | None = None,
) -> list[BenchmarkResult]:
    selected_cases = [
        CASE_BY_NAME[name] for name in (cases or [case.name for case in CASES])
    ]
    configured = _selected_models(models)
    return [
        _run_one(model, case, configured)
        for model in models
        for case in selected_cases
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run disposable security-review cases through the production reviewer service."
    )
    parser.add_argument(
        "--models",
        default="gpt_oss,qwen_general,devstral,bonsai2",
        help="Comma-separated model keys (including benchmark-only bonsai2).",
    )
    parser.add_argument(
        "--cases",
        default=None,
        help="Optional comma-separated case names; defaults to all cases.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    models = [name.strip() for name in args.models.split(",") if name.strip()]
    cases = (
        [name.strip() for name in args.cases.split(",") if name.strip()]
        if args.cases
        else None
    )

    try:
        results = run_benchmark(models, cases)
    except (KeyError, ValueError) as exc:
        _parser().error(str(exc))

    payload = [asdict(result) for result in results]
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if any(result.error is None for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
