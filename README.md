# Local Agent Orchestrator

Local, safety-first coding-agent orchestration for a Git workspace. The
orchestrator uses local `llama-server` models, applies semantic edit operations
deterministically, verifies changes in the target project's environment, and
checkpoints successful work on an isolated agent branch.

It is a local development tool. It does not deploy to production, SSH to a
VPS, merge agent branches, or install dependencies from model-generated
commands.

## Requirements and setup

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Git
- A working `llama-server` binary at the configured default path:
  `~/llama.cpp/build/bin/llama-server`
- Enough RAM/VRAM for the configured models
- Network access the first time a Hugging Face model is downloaded by
  `llama-server` (or a populated local llama cache)

From a fresh clone, run these commands from the repository root:

```sh
uv sync --locked
uv run pytest -q
uv run local-agent-orchestrator
```

The last command is a read-only resource health check. Configuration paths in
`config/settings.yaml` are relative to the current working directory, so run
the CLI from this repository root unless you provide an equivalent layout.

The shipped configuration is in `config/settings.yaml` and
`config/models.yaml`. It requires four active model entries. Bonsai 2 uses the
configured ROCm binary and local GGUF path; both files must already exist on
the machine. Model files are never deleted by the orchestrator. The default
model server path for other models remains code-configured.

## Commands

Show help for every installed command:

```sh
uv run local-agent --help
uv run local-agent-plan --help
uv run local-agent-control --help
uv run local-agent-auto --help
```

### Workestra Control

The local Control plane is a thin browser/API layer over the same execution
engine. It binds to loopback by default and keeps project records in a small
JSON registry; run state, trajectory, metrics, checkpoints, and retrospectives
remain the engine's filesystem artifacts.

```sh
uv run workestra serve \
  --registry ~/.config/workestra/projects.json \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765/`. Register a project with an explicit verifier
argv, import rough Markdown, compile it with Bonsai 2, review the Plan v2
preview, and start the run. Imported Markdown and compiler output cannot supply
shell commands or override the trusted project verifier. The browser may
disconnect and reconnect; SSE replays durable trajectory events with
`Last-Event-ID`.

The MVP exposes project selection, plan import/preview, run state, approvals,
timeline, artifacts/diff, and run history. Pause/cancel are reported as
unsupported until the synchronous engine has a safe interruption primitive;
the Control layer never pretends those actions succeeded.

Run one coding task against a clean target repository:

```sh
uv run local-agent \
  --workspace /path/to/target \
  --task "Implement a small, tested change" \
  --test-command "uv run pytest -q"
```

Run a hand-authored Plan v2 file:

```sh
uv run local-agent-plan \
  --workspace /path/to/target \
  --plan /path/to/plan.json \
  --test-command "uv run pytest -q"
```

The plan schema supports `code`, `docs`, `test`, `review`, `deploy`, and
`manual` tasks. Dependencies are validated for missing references,
self-dependencies, and cycles, then executed in deterministic topological
order. `deploy` and `manual` tasks remain approval-gated. High and critical
risk always requires approval, even when a plan omits `requires_approval`.

Approve and resume a paused plan:

```sh
uv run local-agent-control approve RUN_ID --runs-dir runs
uv run local-agent-control resume RUN_ID \
  --workspace /path/to/target \
  --test-command "uv run pytest -q"
```

`local-agent-auto` asks the external Codex/Sol planner for a Plan v2 JSON
document, validates it through the same deterministic plan validator, and then
executes it. It requires a working `codex` CLI and authentication; it is not
an autonomous deployment path.

## Runtime flow

1. Load and validate trusted local configuration.
2. Require a clean target worktree and create `agent/<run-id>`.
3. Prepare the target verification environment. An existing target `.venv` is
   reused when its verifier is available; otherwise only a locked
   `pyproject.toml` + `uv.lock` project with a declared `dev` extra/group is
   bootstrapped using fixed `uv sync --locked` behavior.
4. Run baseline verification in that same target cwd and isolated environment.
5. Explore repository evidence, then ask a coder for schema-constrained
   semantic operations (`replace_exact`, `create_file`, or `delete_file`).
6. Ground paths and apply exact edits through the deterministic builder. The
   generated diff is checked with `git apply --check --recount --whitespace=error`.
7. Verify the change. Structured baseline triage permits only failures already
   present in the baseline; unknown or new failures fail closed.
8. Run required review and security checks, checkpoint the task, and persist
   state, metrics, trajectory, audit, and retrospective artifacts.

Every model server is scoped to a context manager and stopped before the next
model starts. Failed attempts roll back before retry; failed tasks never
checkpoint.

## Model routing

The four active entries in `config/models.yaml` are routed as follows:

| Entry | Hugging Face model | Role | Reasoning |
| --- | --- | --- | --- |
| `qwen_coder` | `tensorblock/Qwen_Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_M` | Explorer and primary coder | `none` |
| `gpt_oss` | `ggml-org/gpt-oss-20b-GGUF:MXFP4` | Diagnosis, review, optimization | `low` |
| `bonsai2` | `Ternary-Bonsai-2-27B-PQ2_0.gguf` via the configured ROCm server | Deep reasoning, architecture/design review, retrospective | `high` (`xhigh`) |
| `devstral` | `bartowski/mistralai_Devstral-Small-2-24B-Instruct-2512-GGUF:Q4_K_M` | Fallback engineer | `medium` |

GPT-OSS is the primary security reviewer. Qwen3-30B-A3B general and Nemotron
Nano 12B v2 are no longer active routes; their model files may remain on disk
for historical benchmark replay. Qwen3.8 OBLITERATED is experimentally
unsupported and too slow on the current RX 9070 + llama.cpp ROCm setup, so it
is not configured.

Reasoning maps to llama.cpp as `none` → off, `low` → low, `medium` → medium,
`medium_high` → high, and `high` → xhigh. Models run sequentially and the
resource guard blocks startup when another llama process or insufficient memory
is detected.

## Verification and safety boundaries

- The global `--test-command` is the trusted executable verifier. Plan
  `verification` entries are recorded informational metadata and are never
  interpreted as shell commands.
- Target bootstrap accepts only trusted dependency metadata already in the
  target repository. `requirements.txt` and arbitrary model install commands
  are unsupported.
- Existing-file edits require authoritative repository evidence and exact
  single-match replacement. New files must stay inside the workspace.
- Traversal, malformed operations, ambiguous/no-match edits, unsafe paths,
  invalid schemas, and unparseable verification failures are rejected.
- Git validation, rollback, baseline triage, branch isolation, checkpoint
  state, and audit records are mandatory. Model review cannot replace the
  deterministic Git checks.
- The orchestrator does not modify a target's main branch, merge agent
  branches, deploy production, or touch a VPS.

## Artifacts and troubleshooting

Runs are stored under `runs/` by default; analytics are under
`.agent/analytics/`. These directories are runtime evidence and are ignored by
Git for a release commit. Preserve them when diagnosing a run.

Common first-run failures are intentional and fail closed:

- `llama-server binary not found`: build llama.cpp or use the configured path.
- `Another llama process is already running` / insufficient RAM or VRAM: stop
  the competing process or lower resource pressure.
- `Target workspace is not clean`: review and commit/stash target changes
  yourself; the orchestrator never discards them.
- `Unsupported dependency metadata` or bootstrap exit 125: provision a locked
  target project with the supported `dev` dependency declaration.
- `Codex planner failed`: authenticate/configure the external `codex` CLI, or
  use a hand-authored plan.

Known non-blocking limitations are tracked in `PROGRESS.md`: the historical
AI-Assistant scheduler test is a time-sensitive pre-existing baseline failure,
the real semantic-operation sample is still small, and historical runs before
bootstrap-event recording may show unknown bootstrap evidence.

## Release boundary

Before tagging, run `uv sync --locked`, `uv run pytest -q`, and
`uv run python -m compileall -q src tests` from a clean clone. Review
`git status`, ensure only source/config/docs/tests are staged, and keep target
repositories and run artifacts out of the release commit.
