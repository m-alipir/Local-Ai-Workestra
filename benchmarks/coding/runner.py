from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest.mock import patch

from local_agent_orchestrator.agents import devstral_engineer
from local_agent_orchestrator.core.config import load_models, load_settings
from local_agent_orchestrator.models.config import ModelConfig
from local_agent_orchestrator.services import coding_executor
from local_agent_orchestrator.services.coding_context import CodingContext
from local_agent_orchestrator.services.edit_operations import EditOperationError
from local_agent_orchestrator.services.diff_patch import DiffPatchError
from local_agent_orchestrator.services.patches import PatchError
from local_agent_orchestrator.services.git_workspace import GitWorkspace
from local_agent_orchestrator.services.test_runner import CommandResult, run_tests
from local_agent_orchestrator.services.verification_triage import (
    compare_verification,
    establish_baseline,
    summarize_verification,
)


BONSAI_MODEL_NAME = "bonsai2"
BONSAI_BINARY = Path("~/llama.cpp-bonsai-rocm/build/bin/llama-server").expanduser()
BONSAI_MODEL = Path(
    "~/Bonsai-demo/models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PQ2_0.gguf"
).expanduser()
TEST_COMMAND = [
    "/usr/bin/python3",
    "-B",
    "-m",
    "unittest",
    "discover",
    "-s",
    "tests",
    "-q",
]


@dataclass(frozen=True, slots=True)
class CodingCase:
    name: str
    task: str
    files: dict[str, str]
    allowed_paths: tuple[str, ...]


CASES = (
    CodingCase(
        name="normalize_source_name",
        task=(
            "Add a pure function normalize_source_name(value) to src/names.py. "
            "It must strip surrounding whitespace, collapse internal whitespace, "
            "and lowercase the result. Add focused unittest coverage in the existing "
            "tests/test_names.py module. Preserve clean_name and unrelated behavior."
        ),
        files={
            "src/__init__.py": "",
            "src/names.py": (
                "def clean_name(value):\n"
                "    return value.strip()\n"
            ),
            "tests/__init__.py": "",
            "tests/test_names.py": (
                "import unittest\n\n"
                "from src.names import clean_name\n\n\n"
                "class NameTests(unittest.TestCase):\n"
                "    def test_clean_name(self):\n"
                "        self.assertEqual(clean_name('  Ada  '), 'Ada')\n"
            ),
        },
        allowed_paths=("src/names.py", "tests/test_names.py"),
    ),
    CodingCase(
        name="reject_url_credentials",
        task=(
            "Update normalize_url in src/urls.py so HTTP(S) URLs containing an "
            "embedded username or password return None. Preserve public URL "
            "normalization, ports, query parameters, and fragments. Add focused "
            "unittest coverage to tests/test_urls.py without changing unrelated code."
        ),
        files={
            "src/__init__.py": "",
            "src/urls.py": (
                "from urllib.parse import urlsplit, urlunsplit\n\n\n"
                "def normalize_url(value):\n"
                "    parsed = urlsplit(value.strip())\n"
                "    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:\n"
                "        return None\n"
                "    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', '', ''))\n"
            ),
            "tests/__init__.py": "",
            "tests/test_urls.py": (
                "import unittest\n\n"
                "from src.urls import normalize_url\n\n\n"
                "class UrlTests(unittest.TestCase):\n"
                "    def test_public_url(self):\n"
                "        self.assertEqual(normalize_url('https://example.com/a'), 'https://example.com/a')\n"
            ),
        },
        allowed_paths=("src/urls.py", "tests/test_urls.py"),
    ),
    CodingCase(
        name="create_safe_identifier",
        task=(
            "Create src/identifiers.py with a pure function safe_identifier(value) "
            "that lowercases text, replaces every run of non-alphanumeric characters "
            "with a single hyphen, and strips leading/trailing hyphens. Create "
            "tests/test_identifiers.py with focused unittest coverage. Do not modify "
            "existing files."
        ),
        files={
            "src/__init__.py": "",
            "tests/__init__.py": "",
            "tests/test_smoke.py": (
                "import unittest\n\n\n"
                "class SmokeTests(unittest.TestCase):\n"
                "    def test_baseline(self):\n"
                "        self.assertTrue(True)\n"
            ),
        },
        allowed_paths=("src/identifiers.py", "tests/test_identifiers.py"),
    ),
)


@dataclass(frozen=True, slots=True)
class CodingBenchmarkResult:
    model: str
    case: str
    evidence_sha256: str
    task_success: bool
    semantic_edit_valid: bool
    semantic_edit_applied: bool
    verification_success: bool
    verification_classification: str | None
    failure_classes: tuple[str, ...]
    changed_files: tuple[str, ...]
    unnecessary_changes: tuple[str, ...]
    operation_count: int
    latency_ms: float
    baseline_passed: bool | None
    error: str | None = None


def _git(command: list[str], root: Path) -> None:
    subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)


def _workspace(case: CodingCase, parent: Path) -> Path:
    root = parent / case.name
    root.mkdir()
    _git(["git", "init", "-q"], root)
    _git(["git", "config", "user.name", "Coding Benchmark"], root)
    _git(["git", "config", "user.email", "coding-benchmark@example.com"], root)
    for relative, content in case.files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(["git", "add", "-A"], root)
    _git(["git", "commit", "-qm", "baseline"], root)
    return root


def _evidence(case: CodingCase, root: Path) -> CodingContext:
    parts = []
    for relative in sorted(case.files):
        content = (root / relative).read_text(encoding="utf-8")
        parts.append(f"OBSERVED FILE: {relative}\n{content}")
    return CodingContext(
        task=case.task,
        exploration_summary="Deterministic benchmark evidence collected from the clean Git workspace.",
        exploration_transcript="\n\n".join(parts),
        grounded_paths=tuple(sorted(case.files)),
    )


def _changed_paths(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        if line.strip():
            paths.append(line[3:])
    return tuple(sorted(paths))


def _failure_class(exc: Exception) -> str:
    if isinstance(exc, EditOperationError):
        return exc.failure_class
    if isinstance(exc, (DiffPatchError, PatchError)):
        return "patch_validation_failure"
    if isinstance(exc, ValueError):
        return "invalid_schema"
    return "model_error"


def _bonsai_model(configured) -> ModelConfig:
    return configured.models["devstral"].model_copy(
        update={"hf": "bonsai2", "reasoning": "high"}
    )


def _run_one(
    model_name: str,
    case: CodingCase,
    configured,
    settings,
) -> CodingBenchmarkResult:
    started = time.perf_counter()
    failure_classes: list[str] = []
    operations: list[dict] = []
    error: str | None = None
    semantic_edit_valid = False
    semantic_edit_applied = False
    verification_success = False
    verification_classification: str | None = None
    baseline_passed: bool | None = None
    changed_files: tuple[str, ...] = ()
    unnecessary_changes: tuple[str, ...] = ()

    with tempfile.TemporaryDirectory(prefix="coding-benchmark-") as temp:
        root = _workspace(case, Path(temp))
        git = GitWorkspace(root)
        git.assert_repository()
        git.assert_clean()
        evidence = _evidence(case, root)
        try:
            baseline = establish_baseline(root, TEST_COMMAND)
            baseline_passed = baseline.result.passed
        except Exception as exc:
            error = f"baseline: {type(exc).__name__}: {exc}"
            failure_classes.append("baseline_failure")
            baseline = None

        if baseline is not None:
            selected = (
                _bonsai_model(configured)
                if model_name == BONSAI_MODEL_NAME
                else configured.models["devstral"]
            )
            remapped = configured.model_copy(
                update={"models": {**configured.models, "devstral": selected}}
            )
            server_patch = nullcontext()
            if model_name == BONSAI_MODEL_NAME:
                original_server = devstral_engineer.LlamaServer

                def bonsai_server(**kwargs):
                    return original_server(
                        binary=BONSAI_BINARY,
                        model_path=BONSAI_MODEL,
                        flash_attention=True,
                        **kwargs,
                    )

                server_patch = patch.object(
                    devstral_engineer,
                    "LlamaServer",
                    bonsai_server,
                )

            try:
                with (
                    patch.object(coding_executor, "load_models", return_value=remapped),
                    patch.object(coding_executor, "build_coding_context", return_value=evidence),
                    server_patch,
                ):
                    changed = coding_executor.execute_coding_task(
                        case.task,
                        root,
                        coder="devstral",
                        operation_callback=operations.extend,
                    )
                semantic_edit_valid = True
                semantic_edit_applied = True
                changed_files = tuple(sorted(changed))
            except Exception as exc:
                failure_classes.append(_failure_class(exc))
                error = f"coding: {type(exc).__name__}: {exc}"

            if semantic_edit_applied:
                changed_files = _changed_paths(root)
                unnecessary_changes = tuple(
                    sorted(set(changed_files) - set(case.allowed_paths))
                )
                post = run_tests(root, TEST_COMMAND)
                verification = summarize_verification(TEST_COMMAND, post)
                comparison = compare_verification(baseline, verification)
                verification_classification = comparison.classification
                verification_success = comparison.allowed
                if not comparison.allowed:
                    failure_classes.append("verification_failure")

            if not semantic_edit_applied or not verification_success:
                git.rollback()

    return CodingBenchmarkResult(
        model=model_name,
        case=case.name,
        evidence_sha256=hashlib.sha256(
            evidence.as_prompt().encode("utf-8")
        ).hexdigest(),
        task_success=semantic_edit_applied and verification_success,
        semantic_edit_valid=semantic_edit_valid,
        semantic_edit_applied=semantic_edit_applied,
        verification_success=verification_success,
        verification_classification=verification_classification,
        failure_classes=tuple(failure_classes),
        changed_files=changed_files,
        unnecessary_changes=unnecessary_changes,
        operation_count=len(operations),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        baseline_passed=baseline_passed,
        error=error,
    )


def run_benchmark(
    models: list[str] = ("devstral", BONSAI_MODEL_NAME),
    cases: tuple[CodingCase, ...] = CASES,
) -> list[CodingBenchmarkResult]:
    configured = load_models()
    settings = load_settings()
    if any(model not in {"devstral", BONSAI_MODEL_NAME} for model in models):
        raise ValueError("Coding benchmark models must be devstral or bonsai2")
    return [
        _run_one(model, case, configured, settings)
        for model in models
        for case in cases
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare fallback coding models through the existing edit and verification path."
    )
    parser.add_argument("--models", default="devstral,bonsai2")
    parser.add_argument("--cases", default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    selected_cases = CASES
    if args.cases:
        names = {name.strip() for name in args.cases.split(",") if name.strip()}
        selected_cases = tuple(case for case in CASES if case.name in names)
    results = run_benchmark(
        [name.strip() for name in args.models.split(",") if name.strip()],
        selected_cases,
    )
    rendered = json.dumps([asdict(result) for result in results], indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if all(result.error is None for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
