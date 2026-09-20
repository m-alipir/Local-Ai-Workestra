# Local Agent Orchestrator handoff

Read `PROGRESS.md`, inspect `git status --short --branch`, and run the smallest
relevant test before changing code. Update `PROGRESS.md` after every meaningful
change, result, blocker, or architecture decision. Never touch production,
VPS resources, or another repository's main branch without explicit approval.

## Verified v1.0 state

- Unit suite after the release audit: **199 passed**; compileall and offline package build pass.
- Plan v2 dependency ordering, task dispatch, approval, resume, verification
  metadata, rollback, checkpointing, and review behavior are deterministic.
- Semantic operations are schema-constrained and exact-match; path grounding,
  traversal checks, strict Git validation, baseline triage, target environment
  isolation, dependency bootstrap, audit, metrics, trajectory, and retrospective
  authority labeling are active.
- Real AI-Assistant run `7120a13568ea` passed on an isolated agent branch. Its
  scheduler test failure was a pre-existing time-sensitive baseline failure and
  was not changed. AI-Assistant main and production remain untouched.
- Disposable mixed multi-task soak passed for success, blocked failure, and
  approval/resume paths.

The current release audit is recorded at the end of `PROGRESS.md`. Do not use
the historical explorer-context-overflow notes in older progress entries as
current instructions; the compact evidence limits are already applied.

## Runtime architecture

1. `plan_runner.py` validates and topologically orders Plan v2 tasks.
2. `git_workspace.py` requires a clean target and creates `agent/<run-id>`.
3. The target bootstrap/test runner prepares and verifies only the target
   environment from locked trusted metadata.
4. Explorer and coder models receive repository evidence and produce semantic
   operations. The deterministic edit builder, grounding checks, and
   `git apply --check --recount --whitespace=error` enforce safety.
5. Baseline-aware verification, explicit review, checkpoint, rollback, and
   finalization persist state, metrics, trajectory, audit, and retrospective.

Models run one at a time through `LlamaServer` context managers:

| Entry | Role | Reasoning |
|---|---|---|
| `qwen_coder` | explorer and primary coder | none |
| `gpt_oss` | diagnosis/review/optimization | low |
| `qwen_general` | security/design review | medium_high |
| `devstral` | fallback engineer | medium |
| `nemotron` | retrospective only | low |

The exact model IDs and defaults live in `config/models.yaml` and
`config/settings.yaml`. See `README.md` for setup, command examples, supported
task kinds, target bootstrap limits, and safety boundaries.

## Release-audit rules

- Keep run artifacts and preserved agent branches for recovery; do not delete
  them automatically.
- Do not add parser repair, fuzzy matching, arbitrary shell execution, new
  model roles, dependency formats, or deployment behavior without a concrete
  demonstrated blocker.
- For a failure, record the first concrete class, add a focused regression,
  run focused tests, then the full suite and a disposable E2E when relevant.
- The supported target bootstrap is a locked `pyproject.toml` + `uv.lock`
  project with a declared `dev` dependency group/extra. Existing target
  `.venv` tools are reused when safe. `requirements.txt` is unsupported.
- Plan `verification` fields are informational. Only the trusted global
  `--test-command` is executed.

## Useful checks

```sh
uv sync --locked
uv run pytest -q
uv run python -m compileall -q src tests
uv run local-agent --help
uv run local-agent-plan --help
uv run local-agent-control --help
uv run local-agent-auto --help
```

Do not run a real AI-Assistant E2E unless the active milestone explicitly
requires it. A new run must begin by inspecting the target branch and preserving
any user changes.
