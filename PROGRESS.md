# PROGRESS.md — Local Agent Orchestrator

> **Agent rule:** Update this file after every meaningful code change, test result, E2E result, blocker discovery, or architecture decision.
>
> Keep updates concise. Record facts and decisions, not private chain-of-thought. Do not mark a step complete until the relevant test actually passes.

## Goal

Harden `~/local-agent-orchestrator` until it can safely execute a real low-risk coding task against `~/AI-Assistant` end-to-end:
- inspect real repository evidence
- create isolated agent branch
- implement a small task
- apply a valid patch
- run tests
- diagnose/retry safely
- commit only on success
- leave `main` untouched
- produce useful metrics/trajectory/retrospective

Production deployment is **not** part of the current milestone.

## Current status

**Unit baseline:** `260 passed`

**Control-layer integration baseline:** `260 passed` with the repository's isolated Git identity
environment after the Control failure-path fixes.

**Release-readiness verdict:** v1.0-ready candidate after the final audit. No runtime, safety,
packaging, setup, CLI, compile, or cleanup blocker remains. This checkout's `master` branch is
unborn (there is no initial Git commit), so the maintainer must create the release commit before a
`v1.0.0` tag can exist; that is release staging work, not an implementation defect.

**E2E status:** latest real run `7120a13568ea` passed after semantic-operation schema and failure
classification hardening. Baseline verification in the target `.venv` reported `304 passed, 1
failed, 6 skipped`; post-change verification reported `308 passed, 1 failed, 6 skipped`, with the
same structured scheduler failure classified as `preexisting_failures_only`. Qwen produced the
accepted grounded URL-normalization edit on attempt 1 and checkpoint `b89066d5345eab7c26d45c90b6e777b3c9e5b543`
on the isolated `agent/b3357f033b28` branch. `main` remains unchanged.

**Post-routing smoke:** the active four-model fleet passed disposable startup/cleanup, Qwen primary
coding, GPT-OSS security review, Bonsai retrospective, and a minimal Devstral fallback coding task.
Devstral's separate two-file fallback scenario emitted duplicate operations and was rejected before
write as `invalid_operation`; this remains a controlled model-quality limitation, not a safety or
routing failure.

**Next limitations (non-blocking):** the target's time-sensitive scheduler test remains a
pre-existing failure; baseline triage records and safely permits it when no new failure identity
appears. Real semantic-operation measurement still has a small successful-run sample, historical
runs before explicit reused-bootstrap events retain unknown bootstrap evidence, and the external
Codex planner still requires local authentication/availability. Plan v2 review tasks run mandatory
Git validation followed by the existing structured security reviewer; reviewer failure remains
fail-closed. Bonsai Plan Intake may still reject underspecified Markdown with unresolved questions;
bounded requests with explicit input behavior compile successfully in repeated live trials.

**Latest Control smoke:** `a4dbefc5e6d8` passed with real Bonsai Markdown compilation, approval/SSE
resume, target-isolated verification, and real retrospective finalization. No commit was created in
this checkout.

Historical P0 error (resolved):

```text
llama-server returned HTTP 400:
request (11546 tokens) exceeds the available context size (8192 tokens)
```

## Completed

- [x] Local llama.cpp/Vulkan model execution works
- [x] Sequential model lifecycle (`LOCAL_LLM_CONCURRENCY=1`)
- [x] RAM/VRAM/model shutdown resource guard
- [x] Reasoning abstraction: none / low / medium / medium_high / high
- [x] Qwen coder = none
- [x] GPT-OSS = low
- [x] Qwen general = medium_high
- [x] Devstral = medium
- [x] Nemotron = low
- [x] Agent branch isolation (`agent/<run_id>`)
- [x] Clean-baseline checks
- [x] Resume restores saved agent branch
- [x] Approval/resume E2E unit test
- [x] Plan v2 task fields
- [x] Qwen retry loop
- [x] Devstral fallback
- [x] Malformed JSON/diff becomes controlled coding failure
- [x] Unified diff preflight via `git apply --check --recount`
- [x] Reviewer receives repository context
- [x] Security review receives actual git diff
- [x] Expanded task metrics
- [x] `trajectory.jsonl`
- [x] Combined test stdout + stderr in failed task state
- [x] Verification commands run with target workspace cwd and target virtualenv resolution
- [x] Safe target verification bootstrap from locked trusted metadata, with controlled failure
- [x] Baseline-aware verification triage with structured pytest failure comparison and fail-closed
  unknown-result handling
- [x] Per-command checkpoint Git identity fallback when target identity is unconfigured
- [x] Semantic edit-operation protocol with deterministic candidate diff generation
- [x] Auditable requested-operation trajectory events
- [x] Explorer repeated-action protection
- [x] Explorer max-step budget + forced final
- [x] Explorer accepts several noncanonical tool-response shapes
- [x] Deterministic repo bootstrap added before first explorer call
- [x] Bootstrap tolerates non-git temp dirs in tests
- [x] GPT-OSS raw `reasoning_content` fallback removed after causing diagnosis loops
- [x] Full suite restored to `105 passed`

## Completed P0 — explorer context overflow and repository grounding

- [x] Inspect actual current constants in `services/repo_explorer.py`
- [x] Reduce bootstrap size without removing deterministic repo evidence
- [x] Applied limits:
  - `MAX_OBSERVATION_CHARS = 6000`
  - `MAX_TRANSCRIPT_CHARS = 6000`
  - `BOOTSTRAP_FILE_LIMIT = 80`
  - `BOOTSTRAP_CHARS = 3000`
- [x] Run syntax check
- [x] Run focused repo explorer tests
- [x] Run full `uv run pytest -q`
- [x] Confirm still `105 passed`
- [x] Inspect/clean `~/AI-Assistant` branch state safely
- [x] Rerun AI-Assistant E2E
- [x] Inspect result

## E2E success criteria

- [x] Explorer uses real repo evidence
- [x] No context overflow
- [x] No repository-tree request loop
- [x] Qwen produces applicable patch OR Devstral fallback succeeds
- [x] Tests execute with useful stdout/stderr
- [x] Task passes
- [x] Commit created on agent branch
- [x] `main` unchanged
- [x] Metrics valid
- [x] Trajectory valid
- [x] Retrospective artifact written (grounding limitations remain tracked below)

## After first successful E2E

### P1 — Structured output hardening
- [x] Add structured JSON response constraints and authoritative patch path grounding with focused
  regression coverage. Do not weaken `git apply --check --whitespace=error`.
- [x] Research current llama.cpp JSON schema / structured output support
- [x] Prefer schema-constrained explorer actions over parser heuristics
- [x] Replace model-authored unified diffs with schema-constrained semantic edit operations and a
  deterministic current-state snapshot builder; retain strict generated-diff validation.
- [x] Add malformed operation-output tests
- [x] Improve model operation-generation quality after target verification dependencies are
  intentionally provisioned; do not add parser repair heuristics. The current layer constrains
  kind-specific JSON fields, grounds exact excerpts in prompts, and records rejection classes.

### P1 — Verification environment bootstrap
- [x] Prefer an existing target `.venv` when the requested verification tool is available
- [x] Support only locked `pyproject.toml` + `uv.lock` metadata with declared `dev` dependency
  extra/group; reject missing or unsupported metadata
- [x] Run fixed bootstrap commands from target cwd with orchestrator interpreter isolation
- [x] Return controlled structured bootstrap failures before coding/test execution
- [x] Add focused tests, full suite, and disposable target smoke coverage
- [x] Re-run the real AI-Assistant E2E after the explicit dependency-provisioning decision; preserve
  failed-run evidence
- [ ] Resolve or explicitly scope the demonstrated pre-existing target baseline test failure

### P1 — Controlled model/infrastructure errors
- [ ] Decide which `LlamaServerError` cases are retryable
- [ ] Convert safe repo-exploration/model HTTP failures into controlled task failures
- [ ] Preserve HTTP/error body in trajectory

### P1 — Diagnostics
- [x] Persist capped test stdout/stderr excerpts in trajectory events
- [x] Keep `uv` stderr warnings separate from captured test stdout/stderr

### P1 — Retrospective grounding
- [ ] Nemotron treats diagnoses as reports, not repository facts
- [ ] Prevent unsupported routing recommendations from weak/bad evidence

### P2 — Project instructions
- [ ] Read/inject `AGENTS.md` or equivalent repository instructions
- [ ] Add tests

### P2 — Plan/runtime completeness
- [x] Preserve task `verification` as explicit informational metadata; only the trusted global
  verifier command is executable
- [x] Define runtime behavior for `test` and `review` task kinds
- [x] Add cycle detection/topological validation and dependency-blocked/skipped state
- [x] Update Sol planner output schema to Plan v2 and apply the same graph validation
- [x] Map high/critical risk to mandatory approval

### P3 — Performance
- [ ] Measure model startup/shutdown gaps
- [ ] Consider same-model server reuse
- [ ] Add token counts / tok-s / tool counts / files-read metrics
- [ ] Do not optimize at the expense of isolation/correctness

## Model routing reference

| Model | Role | Reasoning |
|---|---|---|
| Qwen3-Coder 30B-A3B Q3_K_M | primary coder + repo explorer | none |
| GPT-OSS-20B MXFP4 | diagnosis/review/optimization | low |
| Bonsai 2 27B PQ2_0 via ROCm | deep reasoning, architecture/design review, retrospective | high (`xhigh`) |
| Devstral Small 2 24B Q4_K_M | fallback coder | medium |

GPT-OSS is the primary security reviewer. Qwen3-30B-A3B general and Nemotron
Nano 12B v2 are retained only in benchmark-history aliases, not active routing.
Qwen3.8 OBLITERATED is experimentally unsupported/too slow on the current RX
9070 + llama.cpp ROCm setup and is not configured.

Reasoning mapping:
- none -> off
- low -> low
- medium -> medium
- medium_high -> high
- high -> xhigh

## Known bad patterns — do not reintroduce

- [ ] Do not use raw `reasoning_content` as reviewer final output
- [ ] Do not let reviewer invent paths absent from repo evidence
- [ ] Do not start explorer with empty evidence
- [ ] Do not stuff the full repo into an 8192-token context
- [ ] Do not retry the exact same explorer tool action repeatedly
- [ ] Do not let malformed model patches crash the whole process
- [ ] Do not hide pytest stdout because stderr has a `uv` warning
- [ ] Do not touch production without explicit approval
- [ ] Do not blindly delete a dirty agent branch
- [ ] Do not give Bash heredoc commands to a Fish-shell user

## Useful commands

Full tests:

```fish
cd ~/local-agent-orchestrator
uv run pytest -q
```

Focused explorer tests:

```fish
uv run pytest tests/test_repo_explorer.py -q
```

Syntax:

```fish
uv run python -m py_compile src/local_agent_orchestrator/services/repo_explorer.py
```

Real E2E:

```fish
uv run python -m local_agent_orchestrator.plan_cli   --workspace ~/AI-Assistant   --plan /tmp/ai-assistant-e2e-plan.json   --test-command "uv run pytest -q"   --runs-dir ~/local-agent-orchestrator/runs-ai-assistant   --analytics-dir ~/local-agent-orchestrator/.agent/analytics-ai-assistant
```

## Progress log

### 2026-09-19
- Unit suite: **105 passed**.
- Deterministic repository bootstrap added to explorer.
- Previous “repository tree unavailable” diagnosis loop was addressed upstream.
- Latest real E2E crashed with **11546 prompt tokens > 8192 context**.
- Confirmed on 2026-09-19: the proposed compact limits were not applied; explorer still used
  12k observation / 14k transcript characters and a 200-file / 10k-character bootstrap.
- Focused pre-change explorer suite: **6 passed**.
- Applied compact evidence limits: 6k observation / 6k transcript characters and an 80-file /
  3k-character bootstrap. Deterministic repository evidence remains enabled.
- Syntax check: `uv run python -m py_compile src/local_agent_orchestrator/services/repo_explorer.py`

### 2026-09-19 — target verification bootstrap design
- Inspected the current launch chain: `tracked_executor` calls `task_executor`, which currently
  calls `run_tests`; both use the target workspace as `cwd`.
- Confirmed `test_runner._verification_environment` removes the orchestrator interpreter/virtualenv
  entries from `PATH`, removes inherited `VIRTUAL_ENV` when no target `.venv` exists, and prepends a
  target `.venv` when present.
- Confirmed the target AI-Assistant repository exposes `pyproject.toml` plus `uv.lock`, with pytest
  declared in the trusted `dev` optional dependency group; its existing `.venv` currently lacks the
  pytest executable. No `requirements*.txt` file is present there.
- Architecture decision: add a small dedicated bootstrap service, initially supporting only locked
  `pyproject.toml` + `uv.lock` metadata and an explicitly declared `dev` group/extra. It will run a
  fixed `uv sync --locked` command in the target cwd with the already-isolated target environment,
  never execute model-provided install commands, and fail before coding/verification when metadata or
  the requested tool is unsupported.
- Implemented the first bootstrap layer in `services/dependency_bootstrap.py`; `task_executor` now
  prepares the target environment before invoking any model and returns a controlled code-125
  failure on bootstrap errors. `test_runner` exposes the existing isolated environment builder for
  reuse; strict test execution remains unchanged.
- Focused bootstrap/runner/task tests: **16 passed**. Coverage includes reuse of an existing target
  pytest executable, missing/unsupported metadata, locked dev bootstrap success/failure, target cwd,
  and removal of orchestrator `PATH`/`VIRTUAL_ENV` from bootstrap.
- Hardened the shared target environment builder to remove inherited `PYTHONHOME`, `PYTHONPATH`,
  `UV_PROJECT_ENVIRONMENT`, and `UV_PYTHON` in addition to the existing interpreter path and
  `VIRTUAL_ENV` filtering. Added task-level coverage proving bootstrap failure stops coding and test
  execution and emits a controlled failure event.
- Focused bootstrap/runner/task tests after the environment hardening: **17 passed**.
- Full suite after bootstrap integration: **135 passed**.
- Disposable `/tmp` target smoke test passed: generated `pyproject.toml` + `uv.lock` bootstrapped via
  `uv sync --locked --extra dev`, then target-isolated `pytest -q` ran successfully (**1 passed**).
  The AI-Assistant repository was not modified.
- Added small portability/metadata hardening: environment builder accepts string roots and strips
  interpreter-selection variables; bootstrap recognizes both PEP 621 `dev` extras and PEP 735
  `dependency-groups.dev`. Focused bootstrap/runner/task tests: **18 passed**.
- Full suite after final bootstrap hardening: **136 passed**.
- Repeated disposable smoke with the configured command shape `uv run pytest -q`: bootstrap returned
  `bootstrapped ('uv', 'sync', '--locked', '--extra', 'dev')`, then target-isolated verification
  passed (**1 passed**). Temporary target was removed; AI-Assistant remained untouched.
- Final workspace check: local-agent-orchestrator contains only its existing untracked project tree;
  AI-Assistant remains on `agent/b3357f033b28` with its pre-existing `AGENTS.md` modification. No
  target repository files were changed by this bootstrap work.
- Added a safety check so a target `.venv` tool symlink resolving outside that environment is not
  treated as available; this prevents an external/orchestrator executable from bypassing bootstrap.
- Focused bootstrap/runner/task tests after symlink hardening: **19 passed**.
- Full suite after symlink hardening: **137 passed**.
- Final disposable E2E after all code/tests passed: `uv run pytest -q` bootstrapped the locked target
  and completed verification with **1 passed**; the temporary target was removed.

### 2026-09-19 — real AI-Assistant E2E preparation
- Current target branch is `agent/b3357f033b28`, pointing at the same commit as `main`; it is not a
  clean worktree because `AGENTS.md` has one pre-existing user/workflow edit. This change will be
  preserved and never discarded while preparing the E2E.
- AI-Assistant matches the supported bootstrap policy: `pyproject.toml` + `uv.lock`, with pytest in
  `[project.optional-dependencies].dev`. Its existing `.venv` has no pytest executable, so the real
  E2E must exercise the new locked bootstrap before verification.

### 2026-09-19 — real AI-Assistant E2E `af1230bb15f4`
- Safely stashed the pre-existing `AGENTS.md` edit, returned the target from stale
  `agent/b3357f033b28` to `main`, and let the run create isolated branch `agent/af1230bb15f4`.
- Bootstrap succeeded from trusted target metadata with the fixed command
  `uv sync --locked --extra dev`; no orchestrator Python, PATH, `VIRTUAL_ENV`, or site-packages
  were used. Verification ran from the target `.venv` and found pytest there.
- Qwen coder attempt 1 produced valid `create_file` semantic operations for `app/utils.py` and
  `tests/test_utils.py`; deterministic diff generation, path checks, and strict git validation
  accepted them and verification ran.
- The first concrete failure was target verification: **309 passed, 1 failed, 6 skipped**. The
  failure is `tests/test_admin.py::test_control_center_scheduler_reuses_persisted_onboarding_preference`,
  which asserts a scheduler timestamp absent from the rendered page.
- Qwen retry 2 requested a no-op replacement and was safely rejected; retry 3 targeted
  `tests/test_utils.py` without authoritative existing-path evidence and was safely rejected.
  Devstral fallback returned a malformed `replace_exact` operation with empty `old_text` and was
  rejected by the strict operation schema. No parser repair or validation weakening was added.
- The run ended failed with no commit after rollback. Run artifacts (`state.json`, metrics,
  trajectory, and retrospective) are preserved in `runs-ai-assistant/af1230bb15f4`; `main` and the
  known stale branch still point to the original commit. The pre-existing `AGENTS.md` edit was
  restored; the failed run branch remains for auditability.
- Independent target verification of the failing admin test reproduced the same assertion on the
  unchanged target source, confirming this is a target baseline failure rather than a bootstrap or
  generated-utility failure.
- Root cause detail: the test hard-codes `2026-09-15T07:30:00+03:00`, while the app lifespan reloads
  the persisted scheduler preference and recalculates `next_run` from the current date before
  rendering. On the current date (`2026-09-19`) the expected timestamp is therefore absent. This
  time-sensitive target test is outside the requested utility task and was not modified.
- The read-only Graphify query updated its tracked query timestamp in AI-Assistant; that generated
  cache-only change was immediately restored. Final target status is again only the pre-existing
  `AGENTS.md` modification.
- Validated failed-run artifacts: `state.json`, plan, metrics, analytics, and all 14 trajectory
  JSONL events parse successfully; retrospective markdown is present. No commit was created.

### 2026-09-19 — baseline-aware verification design
- Execution tracing confirms the safest baseline point is immediately after target bootstrap and
  immediately before the first coding-model attempt inside `task_executor`.
- Baseline and post-change checks will call the same `run_tests(workspace_root, test_command)` with
  the already-prepared target environment. A dedicated verifier adapter will parse only structured
  pytest failure-summary identities; unsupported or unparseable non-zero results fail closed.
- Baseline runs will capture a clean Git head/status and restore the clean baseline through the
  existing `GitWorkspace.rollback()` if verification mutates tracked or untracked non-ignored state.
  The baseline is never treated as an agent edit and cannot enter a checkpoint.
- Comparison policy: clean→clean passes; baseline failures may disappear or remain exactly as the
  parsed set; any new/different/unparseable post-change failure fails. Baseline exit codes and raw
  capped output remain in task results, metrics, and trajectory events.
- Implemented the first baseline triage layer: baseline execution now precedes coding, shared
  pytest identity parsing compares baseline/post-change results, baseline mutations are rolled back,
  and task metrics/trajectory carry baseline identities and comparison classifications. Focused
  verification results and full-suite counts are recorded in the later baseline-triage entries.
- Focused post-change explorer suite: **6 passed**.
- Full suite: **105 passed**; the recorded baseline remains intact.
- AI-Assistant inspection: currently on `agent/b3357f033b28`; worktree and index are clean.
  The prior crashed run left a clean agent branch, so no deletion or cleanup was needed.
- E2E rerun is temporarily blocked: `/tmp/ai-assistant-e2e-plan.json` is absent. Recover the
  exact low-risk plan from prior local run artifacts before launching the model.
- Recovered the unchanged plan from failed run `b3357f033b28` into `/tmp`; it only adds and tests
  `normalize_source_name` and explicitly excludes production/configuration/integration work.
- Corrected E2E launch diagnosis: `LlamaServer` starts and stops its own local server per agent,
  so no listener before `plan_cli` is expected. The earlier standalone health precheck prevented
  the runner from starting; the binary exists and no competing model process is running.
- E2E rerun reached explorer startup but failed before any model request: `llama-server` exited
  with code 1. This is distinct from the prior context overflow; capture its local startup stderr
  before making another code change.
- Captured launch stderr: the sandboxed process cannot bind `127.0.0.1:8080`; socket inspection is
  also denied. The E2E requires unsandboxed local GPU/localhost access, not a code change.
- E2E run `147c71d0d231` launched with approved host-local access and is currently in its first
  Qwen coder attempt. It uses the clean existing `agent/b3357f033b28` branch as its base.
- E2E trajectory confirms the explorer no longer overflowed its context: Qwen completed the first
  coding attempt and produced a rejected, non-applicable patch for `app/ingestion/schemas.py`.
  The runner has started its configured second Qwen attempt.
- Second attempt was also safely rejected (`app/ingestion/schemas.py` already exists in the working
  directory); the third configured Qwen attempt is now running. The failed patch application left
  no tracked AI-Assistant worktree change.
- Third Qwen attempt was safely rejected as a corrupt unified diff. The run has exhausted its Qwen
  retries and is transitioning to the configured Devstral fallback; no context overflow occurred.
- E2E run `147c71d0d231` completed as a controlled failure after all three Qwen attempts and the
  Devstral fallback produced invalid/unapplicable diffs. It ran for 428 seconds, made no worktree
  change or commit, and left `agent/b3357f033b28` clean. `state.json`, `trajectory.jsonl`, and
  metrics JSON are valid. The 8192-token context overflow and repository-tree loop did not recur.
- Architecture decision: retain strict `git apply --check --recount --whitespace=error`; invalid
  model patches must remain controlled failures. Address the next run through prompt/protocol
  grounding and tests, rather than relaxing patch validation.
- llama.cpp investigation: the installed `llama-server` build exposes `-j/--json-schema` and
  OpenAI-compatible `response_format`; its source accepts `type: json_schema` with nested
  `json_schema.schema` and converts that schema to a grammar. Structured output can constrain JSON
  syntax/fields, but cannot guarantee that a unified diff applies, so patch validation remains a
  separate strict gate.
- Next implementation: thread an optional `response_format` through `LlamaServer.chat()` and
  provide schemas for explorer/coder responses, with focused request-shape tests first.
- Implemented optional `response_format` forwarding and JSON schemas for explorer actions and
  Qwen/Devstral `{patch: string}` responses. Focused adapter/coder/explorer/patch tests: **21
  passed**. Strict diff validation is unchanged.
- The first post-change focused rerun failed during test collection because the new schema test
  imported `RESPONSE_FORMAT` from the service instead of the agent module; this was a test-only
  wiring error and no runtime test executed in that invocation.
- Corrected the test import; focused structured-output/patch suite: **22 passed**.
- Full suite after structured-output changes: **107 passed**.
- AI-Assistant branch `agent/b3357f033b28` remains clean and the recovered E2E plan is present.
- Launching the local E2E now with host-local model/GPU and localhost access.
- E2E run `3de563813ffb`: first Qwen response passed JSON-schema parsing but still produced a
  corrupt unified diff (`unexpected line: \"\"\"`); the schema guarantees JSON shape only, as
  expected, and does not guarantee diff correctness. The second Qwen attempt is running.
- Second Qwen attempt produced an applicable patch, but its verification tests failed; the runner
  has started the third Qwen attempt. This confirms structured JSON output improved transport
  validity but cannot replace test verification.
- E2E run `3de563813ffb` then failed on the third attempt with a new context overflow: **8465 >
  8192 tokens**. The overflow occurred after retry diagnostics were added to the coding prompt;
  structured output itself was accepted. Retry-context compaction is now a separate blocker.
- Added bounded retry diagnostics/stdout/stderr (2,000 characters each) and reduced carried coding
  exploration evidence to 6,000 characters. Focused retry/context/structured-output suite: **31
  passed**. The cap test confirms long failures are truncated without weakening patch checks.
- Full suite after retry compaction: **108 passed**.
- The previous E2E left the AI-Assistant branch clean; rerunning the local E2E now with the same
  recovered plan and host-local model access.
- E2E run `4b298112f7ca` first Qwen response again passed the JSON schema boundary but failed strict
  diff validation with the same corrupt-hunk pattern. The second attempt is running; no context
  overflow has occurred so far.
- Second attempt stayed within context but targeted unobserved/mismatched `app/interests/core.py`
  and `tests/test_interests.py`; strict preflight rejected both files. The third Qwen attempt is
  running, and the authoritative-evidence rule remains intact.
- Third Qwen attempt also stayed within context but emitted the same corrupt diff pattern. Qwen
  retries are exhausted; the configured Devstral fallback is next.
- E2E run `4b298112f7ca` completed as a controlled failure after 3 Qwen and 1 Devstral attempt.
  No retry context overflow occurred. JSON-schema output was structurally valid on each usable
  response, but diffs remained corrupt or targeted mismatched/unobserved paths; strict validation
  rejected them and the AI-Assistant branch stayed clean. Run artifacts are valid; no commit or
  production/VPS action occurred.
- Current architecture result: structured output solves JSON transport only. The smallest safe next
  grounding improvement is to carry the explorer's authoritative observed-path set into coding and
  reject any patch target that is neither observed nor explicitly a valid new-file addition before
  `git apply --check`; do not auto-rewrite or sanitize diffs.
- Added explorer-agent request-shape coverage; structured-output focused suite: **23 passed**.
- Full suite after all structured-output and retry-context changes: **109 passed**.
- No further E2E launched after this test-only coverage addition; the latest E2E result remains
  `4b298112f7ca` controlled failure with a clean AI-Assistant branch.
- Implemented authoritative path propagation: successful explorer evidence now records observed
  paths, `CodingContext` carries them, and `apply_unified_diff` performs an early grounding check.
  New-file hunks are allowed when marked from `/dev/null`; existing modifications/deletions/renames
  must be grounded. The existing git preflight command is unchanged.
- Initial grounding focused tests had two empty-repository fixture setup failures because `git
  commit` was called with nothing staged; no implementation assertion ran in those two cases.
  Removed the unnecessary commits; the retry is next.
- Grounding focused suite after fixture and new-file classification fixes: **22 passed**. New-file
  source `/dev/null` is excluded from grounded existing-path requirements; rename/delete coverage
  passes. `uv run ruff check ...` could not run because Ruff is not installed in this environment;
  this is recorded separately from pytest validation.
- Added evidence-flow assertions for explorer `observed_paths` and `CodingContext.grounded_paths`;
  focused grounding suite remains **22 passed**.
- Full pytest suite after authoritative path grounding: **116 passed**.
- The AI-Assistant branch remains clean; launching the required local E2E with host-local model
  access.
- E2E run `ca3c8b9e9c5d` first attempt reached the early diff parser but failed as a malformed
  unified diff (`unexpected line: # Copyright ...`); no patch was applied. The second attempt is
  running. This is a malformed-diff class rather than an ungrounded-path class.
- Second attempt referenced `app/config/sources.py`, which was grounded as an observed existing
  path but failed final git preflight because its hunk did not apply. This separates path grounding
  from hunk correctness as intended; the third Qwen attempt is running.
- Third attempt referenced the same grounded path and failed the unchanged git preflight again;
  Qwen retries are exhausted and Devstral fallback has started.
- E2E run `ca3c8b9e9c5d` completed controlled-failure. Grounding/preflight classes were:
  malformed diff text, grounded existing path with non-applicable hunk, and finally a Devstral
  patch that applied but whose `uv run pytest -q` verification ran under the orchestrator virtual
  environment (`VIRTUAL_ENV=/home/ali/local-agent-orchestrator/.venv`) and failed with 41 import
  collection errors (`app`, FastAPI, SQLAlchemy, and cryptography unavailable). The AI-Assistant
  branch is clean and artifacts are valid; no commit or production/VPS action occurred.
- Per instruction, no parser repair heuristics were added. The remaining generation failure classes
  support investigating a safer edit-operation protocol next; JSON schema and path grounding do
  not guarantee unified-diff correctness.
- Verification-context investigation: `run_tests()` already resolves the supplied workspace root and
  passes it as `cwd`; task, tracked, checkpointed, and plan executors forward that same root. A
  direct reproduction from the orchestrator with `VIRTUAL_ENV` inherited still selected
  `/home/ali/AI-Assistant/.venv` when `uv` was launched with the target cwd. The target environment
  currently has runtime dependencies but no `pytest` executable because its optional dev extras are
  not installed; no dependency installation or target mutation is authorized.
- Added a regression test that creates a target project marker and proves verification commands run
  from that target workspace rather than the orchestrator directory. Focused test execution is next.
- Verification-context focused suite (`test_runner`, task, tracked, checkpointed, and plan runners):
  **22 passed**. The new target-workspace regression passes through the same subprocess launcher
  used by task verification.
- Full pytest suite after verification-context regression coverage: **117 passed**.
- Reran the unchanged local AI-Assistant E2E as `d1448f221318` after verification-context
  coverage. It never reached verification: Qwen attempts produced two corrupt diffs and one
  grounded path with a non-applicable hunk; Devstral produced `app/utils.py`, rejected because the
  response did not establish it as a valid new-file path. The AI-Assistant agent branch remains
  clean and no target dependencies were installed or changed.
- This confirms the remaining failures are patch-generation/grounding classes, not verification
  environment evidence. No parser-repair heuristic will be added; edit-operation generation is
  the next investigation.
- Edit-operation design decision (before implementation): replace the model's `{patch}` response
  with a strict `{operations: [...]}` response. Each operation is one of `replace_exact` (relative
  path, non-empty exact old text, replacement text), `create_file` (relative new path and full
  content), or `delete_file` (relative existing path). The parser will reject unknown fields,
  missing kind-specific fields, duplicate paths, empty exact matches, and malformed JSON; it will
  not repair or normalize model text.
- The deterministic builder will validate every operation against an unchanged workspace snapshot:
  existing replacements/deletions must be present in authoritative explorer paths and on disk;
  replacements must match exactly once; creations must be absent and resolve inside the workspace;
  deletions must target regular files. It will apply validated operations only in a temporary Git
  snapshot of the current touched-file contents, derive `git diff` from those actual contents
  (including intent-to-add new files), then send that generated diff through the existing grounding
  and unchanged strict
  `git apply --check --recount --whitespace=error` gate before applying it to the target.
- The target workspace remains untouched until all operation checks and diff preflight pass; outer
  checkpoint rollback remains the recovery path after tests or later reviews fail. Each attempt
  will persist the validated requested operations and outcome in a run artifact for auditability.
  Explicit rename syntax is deferred; a rename is represented by safe create/delete operations.
- Implemented the first operation-protocol core: strict Pydantic edit-operation models/parser and a
  temporary-worktree builder that validates exact-match/grounding/path rules, derives a Git diff from
  candidate file contents, and routes it through the unchanged unified-diff validator. Integration
  with coder prompts and attempt audit events is still pending; no model-facing behavior is changed
  until those pieces and focused tests are added.
- Initial operation-protocol focused test run: **4 passed, 3 fixture failures**. The three failures
  attempted to commit empty temporary repositories; no operation assertion ran in those cases. The
  fixtures will include a harmless tracked sentinel, matching the existing empty-repository test
  convention, before retrying.
- Operation-protocol core focused tests after fixture correction: **7 passed**. Coverage includes
  grounded replacement, nonexistent existing target, legitimate new file, traversal rejection,
  grounded deletion, zero/ambiguous exact-match safety, and malformed operation responses.
- Switched Qwen/Devstral response schemas, coder instructions, coding executor parsing/application,
  and retry wording to semantic edit operations; added trajectory operation-event support. The
  focused integration suite (operation core, coding executor/context, Qwen schema, task and tracked
  executor): **19 passed**.
- Full pytest suite after semantic edit-operation integration: **124 passed**. The strict existing
  unified-diff validator remains unchanged and is now fed only by the deterministic candidate diff
  builder in the coding path.
- Added bounded stdout/stderr and return-code detail to `tests_finished` trajectory events, plus an
  audit-event regression assertion for requested operations. Focused executor/operation suite after
  this diagnostic change: **19 passed**.
- Semantic-operation E2E `8e25fb6428bc` completed controlled-failure. Attempt 2 produced and
  applied valid `create_file` operations for `app/utils.py` and its focused test; verification then
  failed, while later retries correctly rejected a no-op exact replacement. Devstral also produced
  the same no-op request, so no fallback patch reached verification. The target branch is clean.
- Direct target-context verification confirms `uv run pytest -q` from `/home/ali/AI-Assistant` uses
  `/home/ali/AI-Assistant/.venv` and returns `Failed to spawn: pytest` because target optional dev
  dependencies are absent. The inherited orchestrator `VIRTUAL_ENV` only yields a warning and is
  ignored after target-cwd resolution; no target dependency installation is performed.
- Full pytest suite after trajectory diagnostics and operation audit coverage: **124 passed**.
- Operation E2E review found a retry-state edge case: attempts intentionally retain prior workspace
  edits, so a candidate based only on `HEAD` cannot represent a file created by an earlier failed
  attempt. The safe adjustment is to build each candidate from an exact temporary Git snapshot of
  the current touched-file contents, then diff the requested operation against that snapshot. This
  keeps retries cumulative without mutating the target before final validation; the architecture
  record is updated from a HEAD worktree to this current-state snapshot approach.
- Implemented the retry-safe candidate change: the builder now initializes a temporary Git snapshot,
  copies the exact current contents of all existing operation paths, commits only that snapshot,
  applies semantic operations there, and derives the diff before calling the unchanged target
  validator. Focused operation tests, including editing a file created by a prior attempt: **8
  passed**.
- Full pytest suite after retry-safe snapshot building: **125 passed**.
- E2E `dea471f14889` reached an applicable Devstral patch and captured the verification failure:
  `cwd` was the target, but the child inherited the orchestrator `PATH`/`VIRTUAL_ENV`. Because the
  target `.venv` has no `pytest`, `uv run pytest -q` found the orchestrator pytest executable and
  ran it with the target source, yielding 42 target import-collection errors. This separates cwd
  correctness from environment executable resolution.
- Verification launcher decision: preserve the full inherited environment except remove the active
  orchestrator virtualenv/bin entries from child resolution; when the target has an existing `.venv`,
  prepend its bin directory and set `VIRTUAL_ENV` to that target environment. Do not create or sync
  environments. A missing target pytest must remain a controlled command failure rather than falling
  back to orchestrator pytest.
- Implemented target verification environment isolation in `run_tests()`: target cwd remains
  resolved, active orchestrator virtualenv path entries are removed from child `PATH`, and an existing
  target `.venv` is preferred without creating or syncing it. Focused test-runner suite: **4 passed**.
- Direct launcher check now returns the target-context failure `error: Failed to spawn: pytest` with
  return code 2, rather than running orchestrator pytest against target source. This is the intended
  controlled result while target dev extras remain uninstalled.
- Full pytest suite after verification environment isolation: **126 passed**.
- Final post-fix E2E `2272d141591f`: Qwen attempt 2 produced and applied valid `create_file`
  operations for `app/utils.py` and `tests/test_utils.py`; `tests_finished` recorded only the target
  environment failure (`returncode=2`, `Failed to spawn: pytest`). Later retries were controlled
  exact-match/no-op rejections, with no malformed unified diffs, no orchestrator import errors, no
  commit, and a clean AI-Assistant agent branch. This closes the verification-context blocker while
  leaving target optional dev dependencies untouched.
- Removed an unused operation-model import found during the final source review; no behavior change.
- Final full pytest suite after source cleanup: **126 passed**.
- Final focused safety/source-review suite after removing the temporary snapshot sentinel and
  cleaning imports: **14 passed**.
- Full pytest suite after the final operation-builder cleanup: **126 passed**.
- Source syntax check (`py_compile` over all `src` Python files): passed.
- Strengthened exact replacement matching to count overlapping occurrences, so ambiguous matches
  cannot pass through non-overlapping string-count behavior. Focused operation suite: **9 passed**.
- Full pytest suite after overlapping-match safety coverage: **127 passed**.
- Added canonical-resolved-path collision rejection for aliases such as `app.py` and `./app.py`;
  focused operation safety suite: **10 passed**.
- Full pytest suite after path-alias safety coverage: **128 passed**.

## Completed P0 — verification execution context

- [x] Trace test-command launch through task, tracked, checkpointed, and plan executors.
- [x] Resolve verification cwd from the target workspace and remove orchestrator virtualenv/bin
  fallback from child command resolution.
- [x] Prefer an existing target `.venv` without creating or syncing dependencies.
- [x] Add cwd and target-virtualenv regression coverage.
- [x] Rerun E2E `2272d141591f`: target verification now fails with the precise missing-`pytest`
  command error instead of orchestrator import-collection errors.

## Baseline-aware verification triage and successful-path audit (completed)

- [x] Added a dedicated verification triage service that parses supported pytest failure
  identities, compares baseline and post-change results, and fails closed for unknown or
  uninterpretable non-zero verification results.
- [x] Baseline execution is established after trusted dependency bootstrap and before model
  edits, using the same target workspace, command, and isolated verification environment.
  Git HEAD and workspace mutation are guarded; a mutation is rolled back and rejected.
- [x] Added baseline/post fields to task results, trajectory events, and metrics so raw capped
  command output and structured comparison classifications remain auditable.
- [x] Added focused triage coverage for clean/pre-existing/new/disappearing failures, parser
  failure, same environment/command, and baseline mutation rollback.
- Focused run initially found one test-fixture variable error (`22 passed, 1 failed`); corrected
  the fixture to use its target `tmp_path`. Post-change focused results are pending.
- The first rerun exposed the same fixture's final assertion still referenced the removed local
  variable (`22 passed, 1 failed`); corrected that assertion to use `tmp_path/.venv`.
- Focused baseline/task/runner suite after the fixture corrections: **22 passed**.
- Added a small post-verification execution guard: verifier spawn/OS errors become return code 125
  and are classified as uninterpretable, so the task fails closed instead of escaping the retry
  lifecycle. Focused suite including this regression: **24 passed**.
- Full orchestrator suite after baseline triage and post-verification fail-closed handling:
  **150 passed**.
- Real baseline-triage E2E `5bed3e5ee756` established the baseline in the target `.venv` and
  identified the existing `tests/test_admin.py::test_control_center_scheduler_reuses_persisted_onboarding_preference`
  failure (`304 passed, 1 failed, 6 skipped`). Qwen attempts were safely rejected for malformed
  or non-grounded exact operations; Devstral produced the accepted utility edit. Post-change
  verification ran in the same target environment (`309 passed, 1 failed, 6 skipped`) and the
  comparison correctly classified the sole failure as `preexisting_failures_only`.
- The task then reached checkpointing but Git rejected the commit because no author identity is
  configured in the target environment. The run remains failed at checkpointing, with generated
  files preserved on `agent/5bed3e5ee756` for diagnosis; no merge or deployment occurred.
- Checkpointing diagnosis: commit creation is the first concrete failure after successful baseline
  comparison. The smallest generic fix is to provide deterministic `git -c` author/committer
  fallbacks only when the target has no configured `user.name` or `user.email`; this avoids
  mutating target Git config and preserves any existing configured identity.
- Implemented the checkpoint identity fallback as per-command `git -c` values only for missing
  identity fields; configured target identities remain untouched. Focused Git/baseline/task/runner
  suite: **30 passed**.
- Full orchestrator suite after checkpoint identity handling: **151 passed**.
- Rerun E2E `4d75ed9caf53` passed. Baseline used the target `.venv` and recorded
  `304 passed, 1 failed, 6 skipped`, with the single scheduler failure identified structurally.
  Qwen attempt 2 produced the accepted grounded semantic edits; post-change verification in the
  same environment reported `310 passed, 1 failed, 6 skipped`, and comparison classified the
  unchanged failure as `preexisting_failures_only`. The task checkpointed successfully as commit
  `1285f4bf4cfa3c8865f4d2da6083216c14d44d89` on `agent/4d75ed9caf53`.
- The successful run's metrics, trajectory, analytics, and retrospective were written and include
  baseline/post failure identities and comparison classification. Main remains at
  `6ed822a7c5a3cb549bb8dbd3d517b2bf6e63ba3b`; the accepted diff is only `app/utils.py` and
  `tests/test_utils.py`. The earlier failed-checkpoint run `5bed3e5ee756` remains preserved in
  artifacts, with its generated files kept in a target stash.
- After inspection, the target was returned to its pre-run branch `agent/b3357f033b28` with only
  the pre-existing `AGENTS.md` modification restored. Successful branch `agent/4d75ed9caf53`
  remains unmerged and available for review; no target production or VPS resource was touched.
- Performed a final standard-library import ordering cleanup in `task_executor.py`; no behavior
  change. A verification rerun follows before closing this milestone.
- Final full orchestrator suite after the cleanup: **151 passed**.
- Removed two unused triage type imports found during final source review; no behavior change.
- Final full suite after source cleanup: **151 passed**.

### 2026-09-20 — successful-path audit
- Audited run `4d75ed9caf53`: state/task are passed; baseline and post-change identities match;
  Qwen attempt 2 is the accepted operation event; metrics commit and changed files match commit
  `1285f4bf4cfa3c8865f4d2da6083216c14d44d89`; target `main` is unchanged; only the pre-existing
  `AGENTS.md` edit remains on the preserved working branch.
- The audit found two uncovered invariants: failed verification attempts were not rolled back
  before the next model attempt, and a checkpoint Git error could escape after the task had already
  been marked passed. The smallest safe fix is per-attempt rollback plus controlled checkpoint
  failure state/metrics/trajectory recording.
- Implemented per-attempt Git rollback after rejected coding/verification attempts, explicit accepted
  model/attempt fields, and checkpoint-created/failed trajectory events. Checkpoint errors now mark
  the task failed, roll back the workspace, and still write metrics. Focused checkpoint/task/git/
  metrics/trajectory coverage: **25 passed**.
- Strengthened the focused invariants: accepted model/attempt and committed file list are checked
  against metrics/trajectory, and the fallback Git identity test proves repository config remains
  unset. Focused result remains **25 passed**.
- Full suite after successful-path hardening: **153 passed**.
- Full suite rerun after invariant assertions and checkpoint-event coverage: **153 passed**.
- Disposable checkpoint E2E fixture attempt was rejected before execution because its generated
  `.venv/` and `runs/` directories made the temporary Git workspace dirty. This is a fixture
  setup issue, not a production-path failure; the rerun will ignore `.venv/` and keep run artifacts
  outside the target workspace.
- Corrected disposable fixture reached the checkpoint commit, then finalization failed only while
  starting the optional Nemotron retrospective model in the local environment. The temporary
  target was discarded with no shared-repository effect; the regression rerun will stub only that
  retrospective boundary so checkpoint and artifact invariants can be tested deterministically.
- Disposable clean-repository E2E `c80496fe50fc` passed with a deterministic coder and retrospective
  boundary: baseline/post verification ran, the accepted Qwen attempt was recorded, commit
  `a1087f5c754f190b181bdbc397d246e71492e2e5` contained exactly `app.py`, state/task were passed,
  and checkpoint trajectory/metrics agreed. The temporary target and run artifacts were isolated.
- Hardened Git identity fallback to treat only return code 1 as an absent config key; other
  `git config --get` failures now propagate. Focused checkpoint/task/git suite: **22 passed**.
- Full suite after Git fallback hardening: **154 passed**.
- Disposable clean-repository E2E rerun `3bf04dad325e` passed after the identity hardening. It
  reached commit `d6216565e24f63946f917ff8d33787b571c01350`, with state/task passed, exact
  changed-file/commit agreement, accepted Qwen attempt 1, and checkpoint trajectory/metrics
  agreement. Retrospective generation was isolated behind the same deterministic test stub.
- Programmatic artifact audit passed for `4d75ed9caf53`: state/task passed, nine trajectory events
  parsed, operation paths matched metrics and the branch diff, baseline/post identities matched,
  classification was `preexisting_failures_only`, and Qwen attempt/usage counts agreed. The
  historical artifact predates explicit checkpoint-created events, but its metrics commit and
  trajectory operation evidence remain internally consistent.
- A second audit compared both accepted `create_file` operation contents with the committed blob
  contents; all operation content matched exactly.
- Final focused checkpoint/task/git/metrics/tracked suite after all audit fixes: **26 passed**.

### 2026-09-20 — operation-generation reliability audit
- Read the current semantic-operation parser, deterministic builder, coder prompts/schemas, explorer
  evidence flow, retry lifecycle, metrics, trajectory, and focused tests before changing code.
- Read-only classification of 56 historical `coding_output_rejected` events across 20 AI-Assistant
  runs found: 13 schema/field failures, 15 malformed or non-applicable patch failures from older
  unified-diff runs, 4 no-op operations, 3 exact replacements with no match, 2 empty `old_text`
  operations, and 2 ungrounded paths. The remaining 17 events are mixed legacy patch/preflight
  details and are not safely classifiable from their stored text alone.
- Recent semantic-operation evidence shows the repeatable model errors are omitted `content` on
  `create_file`, empty `old_text`, no-op replacements, and stale/unobserved exact text. Existing
  validation correctly rejects each; no repair, fuzzy matching, path guessing, or retry increase is
  justified.
- The current JSON schema only requires `kind` and `path` and leaves all kind-specific fields
  optional; Pydantic rejects invalid combinations only after the model response. The smallest
  evidence-backed change is to make the response schema discriminated by operation kind, tighten
  the coder instructions for all three operation forms, and record reliable rejection classes per
  attempt.
- Added a discriminated `oneOf` operation schema using llama.cpp-supported `oneOf`, `enum`,
  `minLength`, and `additionalProperties`; `replace_exact`, `create_file`, and `delete_file` now
  require only their valid fields at the structured-output boundary. Added concise kind-specific
  coder instructions and explicit operation failure classes on parser/validation failures and
  rejected verification attempts. Focused generation/operation/task tests: **24 passed**.
- Added a bounded evidence instruction requiring exact contiguous replacement text from observed
  excerpts and complete content for new files. Metrics now persist per-attempt operation failure
  records, while retry prompts carry only the latest class/detail. Focused operation/coder/context/
  task/checkpoint/metrics/tracked tests: **35 passed**.
- Full orchestrator suite after the reliability changes: **156 passed**.
- Disposable semantic-operation E2E `14512a929d31` passed from a clean temporary repository. The
  target-venv test command initially reported one structured baseline failure, the accepted Qwen
  attempt 1 replaced existing `app.py` text exactly, post-change verification passed, and the task
  checkpointed as `620650359202360cf853af8fa224bb0d68f2f279` with only `app.py` changed. Metrics and
  trajectory recorded `baseline_failures_disappeared`, accepted model/attempt, and no rejected
  operation classes.
- Real AI-Assistant generation E2E launch was first rejected before model startup because the
  target still had its known pre-existing `AGENTS.md` edit. The edit was not discarded; it will be
  preserved in a temporary stash during the authorized isolated run and restored afterward.
- Real AI-Assistant E2E `7120a13568ea` passed. After preserving and restoring the pre-existing
  `AGENTS.md` edit, the baseline used the target `.venv` and reported `304 passed, 1 failed,
  6 skipped`; Qwen produced a grounded `replace_exact` for `app/normalize/source_items.py` and a
  new `tests/test_source_items.py` on attempt 1. Post-change verification reported `308 passed,
  1 failed, 6 skipped` in the same target environment, and baseline triage classified the single
  scheduler failure as `preexisting_failures_only`. Security review found no issues; the accepted
  commit is `b89066d5345eab7c26d45c90b6e777b3c9e5b543` with exactly those two files changed. No
  retry or operation failure classes occurred. `main` remains `6ed822a7c5a3cb549bb8dbd3d517b2bf6e63ba3b`.
- The run started from the already checked-out clean `agent/b3357f033b28` branch after the known
  `AGENTS.md` stash, so the executor intentionally reused that existing `agent/*` branch; the
  commit remains off `main` and the pre-existing edit was restored. Future real E2E preparation
  should switch a stale agent branch to `main` before launch when a distinct run branch is desired.
- Restricting the read-only count to six runs that emitted semantic-operation request events gives
  the reliable generation baseline: 16 rejected attempts — 6 `invalid_schema`, 4 `no_op`, 3
  `no_match`, 2 `empty_old_text`, and 1 `ungrounded_path`. The broader 56-event count includes
  legacy unified-diff failures whose stored text cannot be assigned a semantic class safely.
- Generation reliability is improved but measured real-run sample size is one successful first
  attempt; retrospective grounding was the next demonstrated limitation and is now addressed by
  deterministic authority labels and suggestions.
- Post-run artifact audit for `7120a13568ea` passed: state/task are passed, trajectory and metrics
  agree on Qwen attempt 1 and the checkpoint, requested operation content matches the committed
  blobs, changed files match the commit, the preserved `AGENTS.md` edit is restored, the prior
  failed-run stash remains available, and `main` is unchanged.
- Added direct regression assertions for `ungrounded_path`, `path_conflict`, `no_match`, `no_op`,
  `ambiguous_match`, `unsafe_path`, `empty_old_text`, and `invalid_schema` classifications.
  Updated focused generation/operation suite: **39 passed**.
- Full orchestrator suite after the classification regressions: **160 passed**.
- Capped `coding_output_rejected` trajectory detail to the existing 2,000-character retry bound so
  operation failure feedback stays concise without losing its explicit class/path detail. Focused
  suite remains **39 passed**; full suite remains **160 passed**.

### 2026-09-20 — retrospective grounding audit
- Inspected retrospective generation, Nemotron's prompt, metrics/trajectory serialization, baseline
  triage, reviewer diagnosis flow, and recent artifacts. `generate_retrospective()` currently sends
  only raw task metrics to Nemotron; `state.json` and `trajectory.jsonl` are omitted.
- The successful `7120a13568ea` metrics correctly contain `preexisting_failures_only`, baseline and
  post-change identities, accepted Qwen attempt 1, commit, and zero operation failures. Its
  retrospective nevertheless recommended investigating `test_admin.py`, proving that prompt wording
  alone does not enforce the authority hierarchy.
- Architecture decision: add a compact deterministic retrospective context assembled from state,
  metrics, and selected trajectory events. It will label system facts and failure attribution as
  authoritative, keep reviewer diagnoses/model commentary explicitly unverified, and derive the
  final suggestion only from recorded failure classes/events. Missing fields remain unknown.
- Added the deterministic retrospective context and output sections: `AUTHORITATIVE FACTS`,
  `OBSERVED FAILURE`, `MODEL COMMENTARY (UNVERIFIED)`, and `SUGGESTION`. Focused retrospective
  tests cover clean success, baseline-only failure, operation failure classes, conflicting reviewer
  diagnoses, checkpoint failure, rollback uncertainty, unknown evidence, and first-attempt Qwen
  success. Focused result: **11 passed**.
- Hardened retrospective input handling for unreadable trajectory files and malformed state task
  lists; long event details are capped at 600 characters in the compact context. Reused target
  verification environments now emit the same authoritative bootstrap event as newly bootstrapped
  environments, with the status recorded. Retrospective/task focused tests: **23 passed**.
- Full orchestrator suite after retrospective grounding and bootstrap-event hardening: **170
  passed**.
- Added a malformed-state regression to confirm missing task status remains unknown rather than
  being inferred. Retrospective/task focused tests: **24 passed**.
- Replayed stored run `7120a13568ea` from a temporary copy with a deliberately conflicting model
  recommendation. The generated authoritative observation and deterministic suggestion correctly
  classified the scheduler failure as unrelated pre-existing repository debt; the original artifact
  was not modified.

### 2026-09-20 — Plan v2 runtime audit
- Audited `PlanTask`/`ExecutionPlan`, loader, runner, resume flow, state manager, checkpointed and
  tracked executors, verification fields, approval handling, and Sol/Codex planner schema.
- Concrete gaps before implementation: dependency references/self-dependencies were checked but
  cycles were not; input order was trusted instead of topological order; failed or incomplete
  dependencies raised without recording blocked/skipped task state; high/critical risk could bypass
  approval when `requires_approval` was omitted; resume used input order and did not share a complete
  dependency ordering policy; `test` and `review` kinds were accepted by the schema but had no
  runtime executor; `verification` strings were stored only and could not be distinguished from
  enforceable checks; planner JSON described only `request` and task `description` and did not run
  the same graph validation as execution.
- Runtime design decision: retain the trusted global test command as the only executable
  verification command; treat plan `verification` strings as explicit informational metadata;
  execute `test` through the isolated trusted verifier, execute `review` through a fixed read-only
  Git whitespace check, keep `deploy`/`manual` approval-gated, and route `code`/`docs` through the
  existing safe checkpointed coder path.
- Initial compatibility run of the existing plan/resume/planner tests: **20 passed, 1 failed**.
  The remaining failure is the old assertion that `test` kinds must raise as unsupported; the new
  explicit trusted-verifier semantics reached finalization instead, where this fixture had not
  stubbed the optional retrospective model. The test will be updated to assert the new behavior.
- Added focused Plan v2 runtime coverage for topological ordering, dependency failures and blocked
  state, high-risk approval gating, explicit test execution, informational verification metadata,
  unsupported kinds, resume of completed dependencies, and planner graph validation. The focused
  plan/runtime/planner suite now passes **33 tests**.
- Full orchestrator suite after the first Plan v2 runtime implementation: **182 passed**.
- Added fail-closed validation for runtime-constructed unsupported kinds/risks and controlled
  review-command spawn failures. Focused Plan v2 suite remains **33 passed**.
- Added explicit review-task coverage, critical-risk gating, code-task informational verification
  status, and approval trajectory assertions. Focused Plan v2/runtime suite: **36 passed**.
- Planner regression now inspects the emitted JSON schema fields and validates a reversed Plan v2
  dependency graph through the same runtime validator; focused result remains **36 passed**.
- Source and test bytecode compilation passed with `uv run python -m compileall -q src tests`.
- Plan v2 runtime milestone is complete for the existing schema: dependency graph validation and
  ordering, blocked/skipped state, explicit task-kind dispatch, high/critical approval policy,
  trusted verification execution, informational verification metadata, resume ordering, and planner
  schema parity are all covered. No live Sol/Codex planner call was made; authentication/availability
  remains an external prerequisite.
- Full orchestrator suite after Plan v2 validation, dispatch, approval, verification, and resume
  hardening: **185 passed**.
- Disposable multi-task Plan v2 E2E passed from a clean temporary repository (`2bdaf9cc61b9`):
  reversed input was ordered as `code -> review`, the deterministic code step created checkpoint
  `97cf74b094aca3b5954fd2722dda06dfa32639ad`, the dependent fixed Git review passed without a
  second commit, and both task states completed successfully. The temporary target was discarded.

### 2026-09-20 — final reliability hardening audit
- Review-task audit found the prior implementation stopped after `git diff --check`; the existing
  structured security reviewer was available but not used for explicit `review` tasks. The safe
  extension is mandatory committed-diff validation first, followed by `run_security_review()` on
  the actual committed revision. High/critical findings, reviewer parse/model failures, or resource
  errors fail closed; the model never replaces Git validation.
- The only confirmed compatibility leftovers were the unused private
  `test_runner._verification_environment()` alias and the unused plan-runner dependency wrapper;
  both were removed after repository-wide reference checks. The shared target environment builder
  and single plan validator remain the active paths.
- Model lifecycle audit found each existing model integration uses `LlamaServer` as a context
  manager, so start/stop/resource-release behavior remains scoped per coder, reviewer, security,
  optimizer, and retrospective call. No lifecycle abstraction or model role was added.
- Added review blocking/Git-precedence tests and mixed state/approval coverage. Focused review,
  plan, lifecycle, and resource suite: **37 passed**.
- Full orchestrator suite after review-task and compatibility cleanup: **188 passed**.
- Full orchestrator suite after lifecycle cleanup and the context-manager regression: **189
  passed**.
- Full orchestrator suite after review failure-boundary hardening: **190 passed**.
- Final source/test compileall passed. Repository reference scan confirms the removed compatibility
  aliases have no remaining callers; only the active `verification_environment` and
  `prepare_verification_environment` paths remain.
- First disposable mixed-soak attempt was blocked by the fixture itself: its target `.venv/` was
  untracked before plan startup, so the existing clean-workspace guard rejected it. No production
  path or shared repository was affected; the rerun will commit a target `.gitignore` before
  creating the disposable environment.
- Disposable mixed multi-task soak rerun passed with isolated targets: success run `d5cdd093af6f`
  executed reversed-input `code -> review -> test` with one checkpoint and one structured model
  review; failure run `3c7d04d45dca` recorded the failed code task plus blocked dependents; approval
  run `230e893c35cf` paused a critical-risk task, persisted approval, and resumed to a single
  successful checkpoint. Temporary targets and artifacts were discarded.
- Added a context-manager regression proving `LlamaServer.stop()` runs when a model call body
  raises. Focused review, lifecycle, checkpoint, approval, and resource suite: **41 passed**.
- Added fail-closed coverage for committed-file discovery and model-review failure after mandatory
  Git validation. Focused review/lifecycle suite: **42 passed**.
- `ruff` is not installed in the target orchestrator environment, so lint validation was not
  available; compileall and pytest remain the verified checks.
- Release-readiness audit started: `uv run pytest -q` passed **190 tests** and
  `uv run python -m compileall -q src tests` passed. Packaging/CLI inspection found that the
  only declared `local-agent-orchestrator` script still points to the template greeting, while
  the four operational CLI modules are not exposed as installable scripts; this is a concrete
  fresh-install release blocker under investigation.
- Runtime cleanup audit found a concrete model-start failure defect: `LlamaServer.start()` could
  leave its captured resource baseline uncleared when `Popen` failed, and `stop()` returned early
  when no process existed. The fix will keep the original startup error while always releasing
  the baseline, with focused regression coverage.
- Fixed the model-start cleanup defect: startup failures now always call cleanup, preserve the
  original exception, and release the captured resource baseline even when no process was spawned.
  Focused lifecycle result: **7 passed** in `tests/test_llama_server.py`.
- Release packaging is now explicit: version `1.0.0`, meaningful project metadata, and installable
  `local-agent`, `local-agent-plan`, `local-agent-control`, `local-agent-auto`, and health-check
  `local-agent-orchestrator` entry points. `uv lock --offline` and `uv sync --locked` both passed;
  all five `--help` commands work. CLI service failures now return concise `error:` messages
  without tracebacks. Focused CLI/lifecycle result: **18 passed**.
- Added fail-closed model-config validation so missing runtime entries are reported together before
  any model starts. Focused release/config/lifecycle tests: **21 passed**.
- Replaced the empty README with fresh-clone setup, architecture/runtime flow, command usage,
  five-model routing/reasoning, supported/unsupported behavior, safety boundaries, troubleshooting,
  and release checks. Replaced stale HANDOFF instructions with the current verified state and
  ignored runtime evidence/cache directories in `.gitignore`.
- Final disposable release smoke `ff143a5b9985` passed from a temporary Git repository: a
  committed change reached the explicit review task, mandatory Git validation and the structured
  reviewer boundary passed, the task state was `passed`, and no extra checkpoint was created.
  The temporary target and script were removed; no shared or target repository was changed.
- Post-audit validation: full suite **199 passed** and `uv run python -m compileall -q src tests`
  passed. The count includes the cleanup, packaging, CLI, and model-config regressions.
- Offline package build passed for `local_agent_orchestrator-1.0.0.tar.gz` and
  `local_agent_orchestrator-1.0.0-py3-none-any.whl`; generated `dist/` is release-ignored and will
  be removed after this check.
- Repeated the offline wheel/sdist build after the final health-check change; both artifacts still
  build successfully, and generated `dist/` was removed again.
- Final setup/CLI pass: `uv sync --locked`, the health check (`Guard: SAFE`), and all four
  operational `--help` commands passed. Final hygiene scan found no stale TODO/debug/template
  markers or secrets in source/config/docs; only ignored runtime/cache/venv artifacts remain.
- Configuration truthfulness review found four shipped settings fields with no runtime readers:
  `max_concurrency`, `checkpoint_after_task`, `wait_between_models_sec`, and `models_config`.
  They represented no supported behavior, so the smallest safe release fix is to remove them from
  the schema and shipped YAML; sequential execution, per-task checkpointing, and the fixed model
  config path remain enforced by the active code.
- Removed those four inert settings fields from `models/config.py` and `config/settings.yaml`;
  focused config result: **3 passed**. Existing user files with the old keys remain harmless because
  Pydantic ignores unknown compatibility keys, while the shipped configuration now states only
  supported controls.
- Final post-configuration-removal validation remains green: full suite **199 passed** and
  `uv run python -m compileall -q src tests` passed.
- Rebuilt the 1.0.0 wheel and source distribution offline after the configuration cleanup; both
  passed and generated `dist/` was removed.
- Final status scan shows only the intended source/config/docs/test tree plus ignored runtime,
  cache, and virtual-environment artifacts; no release build directory, stale setting references,
  TODO/debug/template markers, or repository secrets remain. Git `master` is still unborn by design
  in this sandbox; no commit or tag was created.
- Previous final-reliability limitations remain non-blocking: the known time-sensitive AI-Assistant
  scheduler baseline failure, small operation-generation sample, historical unknown bootstrap
  evidence, and parallel plan/resume dispatch paths. No production/VPS or AI-Assistant main
  changes were made.

### 2026-09-20 — v1.0 release-readiness audit
- Full audit completed without touching AI-Assistant main or production/VPS. Fresh-clone setup was
  verified with `uv sync --locked`; all operational CLI entry points and `--help` output work, and
  invalid workspace/plan/run/model inputs now produce concise fail-closed `error:` messages.
- Configuration review confirmed relative config paths, strict Pydantic validation, explicit five-
  model presence checks, resource thresholds, and sequential model lifecycle. The llama-server
  default remains `~/llama.cpp/build/bin/llama-server` and is documented; no secrets, debug output,
  stale TODOs, or machine-specific source paths were found. Runtime evidence, caches, and virtual
  environments are ignored while preserved on disk for auditability.
- Fixed one concrete cleanup defect: failed model startup now releases the captured resource
  baseline even when `Popen` never creates a process. Added lifecycle regression coverage.
- Added installable scripts and versioned package metadata (`1.0.0`), replaced the empty README
  with setup/runtime-flow/safety/routing documentation, and replaced stale HANDOFF instructions.
- Health-check CLI now exits non-zero when the resource guard blocks or configuration loading
  fails, instead of printing a blocked state with success status. Focused release/config/CLI/
  lifecycle tests: **22 passed**. Full suite: **199 passed**. Source and
  test compileall passed. Offline wheel and sdist build passed. `ruff` remains unavailable in the
  environment, so lint was not run.
- Final disposable review smoke `ff143a5b9985` passed from a temporary Git target and was removed.
- Release classification: **no implementation blockers**. **Release-staging blocker:** this
  sandbox has no initial Git commit (`master` is unborn), so a maintainer must create the first
  release commit before tagging. Non-blocking limitations are the known AI-Assistant scheduler
  baseline failure, small real semantic-operation sample size, unknown bootstrap evidence in old
  runs, external Codex planner authentication, and the documented local llama.cpp/model resource
  prerequisite.
- Recommended staging procedure (after review in a clean clone):
  `uv sync --locked`; `uv run pytest -q`; `uv run python -m compileall -q src tests`;
  `git add .gitignore .python-version HANDOFF.md PROGRESS.md README.md config pyproject.toml src tests uv.lock`;
  `git diff --cached --check`; `git commit -m "Release v1.0.0"`;
  `git tag -a v1.0.0 -m "local-agent-orchestrator v1.0.0"`; then verify with
  `git show --stat --oneline v1.0.0` and `git status --short`.
- Next milestone: maintainer release staging/tagging, followed by only demonstrated reliability
  work (no speculative feature expansion).

### 2026-09-20 — disposable security-review benchmark
- Added an isolated `benchmarks/security_review/` harness with five temporary Git fixtures covering
  command injection, path traversal, secret exposure, a combined shell/path boundary, and a clean
  control. It invokes the existing `services.security.run_security_review` interface; production
  routing and AI-Assistant are unchanged. Selected configured models are remapped only inside the
  benchmark process to the service's existing default slot.
- The runner records expected/detected categories, misses, false positives, finding titles,
  per-case latency, and controlled model/server errors. Focused benchmark tests: **5 passed**.
- Real local-model benchmark results: `qwen_general` completed all five cases with 4/5 category
  cases correct, no false positives, and one missed `path_traversal` in the combined boundary;
  per-case latency was **60.9–67.3s**. `gpt_oss` completed all five with all expected categories,
  no false positives, and **4.9–41.3s** per case. `devstral` detected the three standalone
  vulnerabilities, missed the combined case's `path_traversal`, and raised an unclassified finding
  on the clean control; its latency was **23.8–53.8s** per case.
- The first evaluator pass exposed that unmatched model findings were being dropped. Added an
  `unclassified` category so clean-control false positives remain visible. Focused benchmark tests
  remained **5 passed**; the devstral clean-control rerun recorded one `unclassified` false
  positive at **36.0s**.
- Full orchestrator suite after adding the benchmark: **204 passed**. Benchmark sources compiled
  successfully, and the final process scan found no lingering llama-server or benchmark process.
- Benchmark CLI help was verified; temporary JSON reports remain under `/tmp` only and no generated
  benchmark output was added to the repository.
- Aggregated report `/tmp/security-review-benchmark.json` contains 15 model/case rows: expected
  categories were 5 per model; `gpt_oss` matched 5/5 with 0 false positives, while `qwen_general`
  and `devstral` each matched 4/5. `devstral` recorded one clean-control `unclassified` false
  positive; latency ranges were qwen **60.9–67.3s**, GPT-OSS **4.9–41.3s**, and Devstral
  **28.9–53.8s**.

### 2026-09-20 — Bonsai benchmark adapter design
- Inspected the existing security-review path: the benchmark calls `services.security.run_security_review`, which constructs the normal `SecurityReviewer` and `LlamaServer`; production routing currently selects `qwen_general`.
- The Bonsai ROCm binary supports local `-m/--model`, full offload via the existing `-ngl 99`, and Flash Attention via `-fa on`. The smallest safe integration is optional `LlamaServer` adapter arguments for a local model path and Flash Attention, with defaults preserving the existing `-hf` command; the benchmark will patch only the reviewer’s server symbol for `bonsai2`.
- No production model config or routing change is planned. Benchmark fixtures and expected results remain unchanged.
- Added optional local-model/Flash Attention support to `LlamaServer`: local paths use `-m`, optional Flash Attention uses `-fa on`, and full GPU offload remains the existing `-ngl 99`; default Hugging Face startup is unchanged.
- Added a benchmark-only `bonsai2` alias that patches only the security reviewer’s server constructor to the supplied ROCm binary/model. Production routing/configuration is unchanged.
- Focused adapter and benchmark tests: **14 passed**. The adapter test asserts local `-m`, `-ngl 99`, and `-fa on` command construction.
- Full orchestrator suite after the Bonsai adapter/alias changes: **206 passed**; source and benchmark compileall passed.
- Bonsai preflight passed: the supplied ROCm binary is executable (16,000 bytes), the supplied PQ2_0 GGUF exists (7,206,168,928 bytes), `--help` confirms `-fa/--flash-attn [on|off|auto]`, and no existing `llama-server` process was present before launch.
- Initial Bonsai five-case launch reached the ROCm server but all reviews failed closed with HTTP 500 before model output: the selected security model carried `medium_high`, and the shared mapping emitted `--reasoning-effort high`; Bonsai's template accepts only `low`, `medium`, and `xhigh`. No detections were counted from these errors. This is a benchmark-only reasoning compatibility issue; no safety or routing behavior was weakened.
- The initial run exited cleanly; a follow-up process check found no lingering `llama-server` or benchmark process.
- Focused regression after the Bonsai reasoning compatibility fix: **15 passed**. The benchmark now maps only Bonsai's selected config to the existing `high → xhigh` adapter level; other model configs and production routing remain unchanged.
- Corrected Bonsai run across the unchanged five fixtures completed with the supplied ROCm binary, local PQ2_0 model, `-ngl 99`, Flash Attention `-fa on`, and `xhigh` reasoning effort. It detected all five expected vulnerability categories: command injection, path traversal, and secret exposure standalone; both command injection and path traversal in the combined case. No category misses or false positives occurred.
- The clean-control case returned no JSON object after **45.1s** and was recorded as a controlled reviewer error (expected empty findings, no inferred detection). Other Bonsai latencies were **7.3–19.9s**; all five cases completed in **96.3s** total. No model or benchmark process remained afterward.
- Updated the benchmark README with the Bonsai-only alias and exact ROCm/local-model flags. Aggregated `/tmp/security-review-benchmark.json` now contains 20 rows for `gpt_oss`, `qwen_general`, `devstral`, and `bonsai2`.
- Four-model aggregate: Bonsai **5/5 expected categories, 0 misses, 0 false positives, 1 clean-control parse error, 7.3–45.1s**; GPT-OSS **5/5, 0 misses, 0 false positives, 4.9–41.3s**; Qwen general **4/5, 1 miss, 0 false positives, 60.9–67.3s**; Devstral **4/5, 1 miss, 1 false positive, 28.9–53.8s**.
- Final validation after Bonsai integration: focused adapter/benchmark tests **15 passed**, full orchestrator suite **207 passed**, and `uv run python -m compileall -q src benchmarks/security_review` passed. `git status` shows only intended PROGRESS, adapter/test, and benchmark files; generated reports remain in `/tmp` and no generated files are in the benchmark tree.

### 2026-09-20 — retrospective benchmark design
- Inspected `build_retrospective_context()` and `NemotronRetrospective.run()`, plus stored run `7120a13568ea`. The same compact authoritative JSON context will be supplied to both models; lower-authority commentary remains included but is not treated as fact.
- The benchmark will be isolated under `benchmarks/retrospective/`, use the existing `NemotronRetrospective` interface, and patch only its server constructor for Bonsai's ROCm binary/local GGUF with full offload and Flash Attention. Production routing and the normal retrospective service remain unchanged.
- Scoring will report deterministic evidence checks: section/output parse validity, baseline-failure attribution, supported versus unsupported claims, evidence-aligned root-cause usefulness, actionable suggestions, and latency. It will not infer a concrete root cause absent from the stored authoritative evidence.
- Added `benchmarks/retrospective/`, a disposable harness that calls the existing `NemotronRetrospective.run()` interface for `nemotron` and benchmark-only `bonsai2` on one identical `build_retrospective_context()` JSON input. It records a context digest, raw output, latency, section validity, grounded facts, unsupported claims/suggestions, and evidence-aligned root-cause status.
- Focused retrospective benchmark tests: **4 passed**. Tests cover grounded baseline-aware output, baseline hallucination/routing claims, malformed sections, and identical model input.
- Real comparison on `7120a13568ea` completed for both models with identical context SHA-256 `3a414c0fb91aaecb6e861b06aee34ede820bf4db059a4a67d47db4e892b74771`: Nemotron latency **49.9s**, Bonsai latency **45.2s**, both produced valid five-section output and no model-call errors.
- First evaluator pass conservatively marked Nemotron's recommendation to address the scheduler failure in a “dedicated task” as unsupported. The output explicitly framed it as unrelated pre-existing debt, so the evaluator must distinguish a separately scoped debt suggestion from an agent-task recommendation before final scoring.
- Focused tests after the evidence-aware evaluator correction: **4 passed**. Separate/debt-tracking recommendations are accepted only when explicitly framed as a dedicated/separate task; agent-task remediation remains unsupported.
- Replayed the stored model outputs with the corrected evaluator (no model rerun): both Nemotron and Bonsai are now `grounded`, have no unsupported claims or suggestions, give evidence-aligned baseline attribution with the concrete underlying cause remaining unknown, and recommend only separate tracking of the baseline debt. Bonsai grounded 5 recorded facts versus Nemotron 3; both outputs were well-formed.
- Final validation after the retrospective benchmark: full orchestrator suite **211 passed**, `uv run python -m compileall -q src benchmarks` passed, `git diff --check` passed, and no `llama-server` or retrospective benchmark process remained.
- Remaining benchmark limitation: this comparison covers one stored successful workload (`7120a13568ea`); the deterministic evaluator can only judge claims against facts recorded in that context and intentionally leaves any concrete scheduler root cause unknown.

### 2026-09-20 — coding-model benchmark design
- Inspected the existing coding path: `execute_coding_task()` builds repository context, invokes the selected coder agent, parses the shared semantic-operation schema, applies deterministic edits/strict Git validation, and returns changed paths. Verification triage is available through `establish_baseline()`, `run_tests()`, `summarize_verification()`, and `compare_verification()`.
- Historical trajectory patterns selected for measurement are invalid operation/schema output, exact replacement `no_match`, `no_op`, ungrounded paths, and verification failure; successful historical edits include grounded existing-file replacements and legitimate creation of focused test files.
- The disposable benchmark will snapshot identical repository evidence once per fixture, run both Devstral and benchmark-only Bonsai through the existing `execute_coding_task()` path using the fallback coder wrapper, then use existing baseline/post-change verification comparison. It will report operation validity/failure classes, changed-path scope, verification, task success, and latency without changing routing.
- Added `benchmarks/coding/`, a disposable three-fixture harness using the existing fallback `DevstralEngineer` wrapper, shared semantic operation parser/applicator, and verification triage. Bonsai is injected only as a benchmark-local server/model override; deterministic evidence is snapshotted once and reused for both models.
- Focused coding benchmark tests: **4 passed**. Fixtures cover existing-file replacement, URL credential hardening, legitimate new-file creation, clean Git state, and operation failure-class preservation.
- Coding benchmark preflight passed: Bonsai ROCm binary and 27B PQ2_0 GGUF exist at the requested paths, no stale `llama-server` process was present, and the benchmark CLI help renders correctly.
- First coding benchmark launch was blocked before model calls: the temporary repositories lacked ignore rules, so `unittest` bytecode appeared as untracked baseline mutations; the new-file fixture also had zero baseline tests, which the verifier correctly treated as uninterpretable. The benchmark now uses `python -B` and a tracked baseline smoke test in the new-file fixture. Focused tests remain **4 passed**, and all three fixture baselines now pass without workspace mutation.
- Corrected coding benchmark run completed: Devstral succeeded on **3/3** tasks with valid/applied semantic edits and passing verification; Bonsai succeeded on **1/3**. Bonsai's two controlled failures were `invalid_schema`: no JSON object for the URL task and unterminated JSON for the new-file task. No verification ran after those rejected edits, and neither model produced unnecessary changed paths.
- Per-task latency: Devstral **56.6–100.9s** (224.0s total); Bonsai **46.6–48.6s** (141.9s total). All baselines passed and no `llama-server` process remained afterward.
- Added per-case evidence SHA-256 to the benchmark report and a focused regression proving identical fixture evidence digests across model runs. Focused coding benchmark tests: **5 passed**. Existing `/tmp/coding-model-benchmark.json` was replayed with the digests; no model rerun was needed.
- Final validation initially exposed an environment-only full-suite failure in the existing Git identity fallback test: this shell has a pre-existing global `~/.gitconfig` identity, so GitWorkspace correctly discovered that identity and did not use its command-scoped fallback, while the test assumes no global identity. The benchmark did not write Git config. No production or safety change is justified; validation will rerun with global Git config disabled for the test environment.
- Final validation with `GIT_CONFIG_GLOBAL=/dev/null` (the test's intended no-global-identity condition): focused coding benchmark tests **5 passed**, full suite **216 passed**, compileall and `git diff --check` passed, and no model/benchmark process remained. The unmodified default-shell full-suite failure remains classified as a pre-existing environment configuration issue, not a benchmark or production defect.

### 2026-09-20 — final fleet routing design
- Active fleet will contain four entries: `qwen_coder`, `gpt_oss`, `bonsai2`, and `devstral`. `qwen_general` and `nemotron` will be removed from `config/models.yaml` and required runtime entries.
- `services.security` will use GPT-OSS as the primary security reviewer. The existing retrospective interface will use active `bonsai2`; its trusted model entry carries the supplied ROCm binary, local GGUF path, full offload/Flash Attention settings, and high reasoning (mapped to `xhigh`).
- Historical security/retrospective benchmark aliases may retain the removed model IDs only as explicit benchmark-only legacy specs, never as active routing entries, so stored benchmark workloads remain rerunnable. Qwen3.8 OBLITERATED will be documented as experimentally unsupported/too slow on the current RX 9070 + ROCm setup and will not be configured.
- Focused fleet/config/routing/benchmark tests initially exposed two incorrect test spies; corrected them to inspect patched constructor calls. Final focused set: **30 passed**. It verifies four active model entries, GPT-OSS security routing, Bonsai retrospective routing/settings, and legacy benchmark aliases.
- Added a focused regression proving the active Bonsai retrospective model forwards its configured local binary, GGUF path, Flash Attention, and reasoning settings into `LlamaServer`. Routing-focused subset: **9 passed**.
- Full isolated validation after fleet routing changes: **217 passed** with `GIT_CONFIG_GLOBAL=/dev/null`; compileall for `src`, `tests`, and `benchmarks` passed; `git diff --check` passed.
- The default-shell full suite still reports **216 passed, 1 failed** only in the pre-existing fallback-identity test because `/home/ali/.gitconfig` supplies a global user identity. With the intended isolated test environment (`GIT_CONFIG_GLOBAL=/dev/null`), the same suite is **217 passed**; no routing change or benchmark modified global Git configuration.
- Clarified that the existing `NemotronRetrospective` class name is retained as the retrospective interface; active model selection now supplies Bonsai 2 from trusted configuration. No Nemotron model entry remains in runtime configuration.
- Final fleet validation: focused routing/benchmark set **31 passed**, isolated full suite **217 passed**, compileall for `src`, `tests`, and `benchmarks` passed, `git diff --check` passed, and no `llama-server` process remained.
- Updated HANDOFF's verified suite count to the final **217 passed** result.

### 2026-09-20 — final post-routing smoke design
- The active configuration resolves exactly four runtime entries: `qwen_coder`, `gpt_oss`, `bonsai2`, and `devstral`; security routes to GPT-OSS and retrospective routes to Bonsai with the configured ROCm/local-model flags.
- The final smoke will use disposable temporary Git workspaces and a synthetic retrospective run. It will exercise Qwen primary coding, Devstral fallback-coder execution, GPT-OSS security review, and the active Bonsai retrospective path sequentially, checking outputs and server cleanup after each model.

### 2026-09-20 — final post-routing smoke: fallback coding failure
- The disposable smoke reached the real coding pipeline and model cleanup guard.
- Qwen's primary coding path completed far enough to hand off to the separate Devstral fallback case; the script stopped on Devstral's response.
- Devstral returned duplicate semantic operations for the same path. Existing `EditOperationsResponse` validation rejected this as `invalid_operation` before any workspace write, and the `llama-server` process was cleaned up.
- This is a controlled fallback-model generation failure, not a validation or isolation regression. The remaining GPT-OSS security and Bonsai retrospective smoke paths still require independent execution.

### 2026-09-20 — final post-routing fleet smoke result
- Active routing preflight resolved exactly `qwen_coder`, `gpt_oss`, `bonsai2`, and `devstral`; the configured Bonsai ROCm binary/model and Flash Attention flag were present. No stale model server existed before or after the smoke.
- Qwen primary coding passed in a disposable Git repository: grounded semantic edits applied, `git diff --check` passed, and the resulting function probe passed.
- Devstral's two-file fallback scenario was rejected safely as `invalid_operation` because its response contained duplicate operations for one path; no write escaped the disposable workspace. A minimal single-file fallback scenario then passed with one grounded edit, `git diff --check`, semantic probe, and clean shutdown.
- GPT-OSS security review passed through `run_security_review()` and detected the expected high-severity `subprocess.run(..., shell=True)` command-injection finding.
- Bonsai 2 retrospective passed through `generate_retrospective()` using the active ROCm/local model configuration; it wrote a non-empty authoritative-context retrospective and shut down cleanly.
- The smoke therefore validates startup, routing, cleanup, primary coding, security review, retrospective, and fallback behavior. The duplicate-operation case remains a recorded model-quality limitation handled by existing fail-closed validation.
- Post-smoke validation passed: 31 focused routing/benchmark tests, full suite **217 passed**, `python -m compileall -q src tests benchmarks`, and `git diff --check` with `GIT_CONFIG_GLOBAL=/dev/null`.
- Removed only compile-generated benchmark `__pycache__` directories after validation; no model files, target repositories, AI-Assistant, or production resources were changed.
### 2026-09-21 — Workestra Control architecture and ownership
- Read `Workestra_Control_Brief.md`, `PROGRESS.md`, `README.md`, and `HANDOFF.md` before implementation.
- Control layer boundary: the existing orchestrator remains the sole execution engine and safety authority. New control-facing application services may call existing plan/run services, but will not duplicate CLI parsing or subprocess execution.
- Ownership for parallel work: engine/application boundary audit (existing services and audit report); Plan Markdown intake/compiler (`services/plan_intake.py`, `models/plan_intake.py`, dedicated tests); local Control API/SSE (`control_api/`, API tests, CLI wiring); minimal UI (`web/` only); lead-owned safety/regression/E2E tests and `PROGRESS.md`.
- Imported Markdown is untrusted. The compiler may produce only a Plan v2 candidate; existing deterministic validation remains mandatory, plan verification metadata remains informational, and no imported command is executable.
- Local API defaults to loopback, browser disconnect must not alter durable run state, and all event/timeline data comes from authoritative run artifacts or a bounded application event journal.
- Static UI milestone started with `web/index.html`, `web/app.js`, and `web/style.css`; the first focused asset test exposed only an overly literal assertion for the composed `/api` prefix, with no runtime defect.
- UI asset focused tests after correcting that assertion: **2 passed**. The UI remains static/dependency-free and renders event/artifact data with `textContent`, not HTML.
- First integrated intake/application/API focused run reached **15 passed, 1 failed**: SSE replay returned the correct event ID/payload but compact JSON omitted the spaces asserted by the API contract test. This is serialization formatting only; replay and disconnect safety behavior were otherwise exercised.
- Stream B Plan Intake milestone complete: `PlanIntake` preserves untrusted Markdown, Bonsai 2 emits a strict candidate schema, existing Plan v2 validation remains mandatory, high/critical risk is approval-forced, and unsafe deploy/VPS/main-merge/shell/dependency-install intent is rejected. Stream-focused Plan Intake + Plan v2 tests: **30 passed**. Full-suite integration waits for Stream A's application files.
- Stream A application boundary milestone complete: project registry persists only project paths and trusted verifier argv; start/resume/approval/artifact reads delegate to the existing engine; artifact traversal is rejected. Pause/cancel remain explicitly unsupported because the current synchronous engine has no safe interruption primitive. Focused boundary tests: **5 passed**; compile passed.
- Integrated control-layer focused tests after Stream A/B and API serialization correction: **19 passed** (`plan_intake`, `control_application`, `control_api`, and static UI assets). SSE replay now preserves event IDs and readable JSON payloads.
- Stream C local API milestone complete: stdlib loopback HTTP, durable artifact/event reads, `Last-Event-ID` SSE replay, bounded JSON/path validation, and background dispatch through an injected application service. Stream-focused API tests: **9 passed**. The next integration slice must connect project/plan/run lifecycle payloads and static UI serving without duplicating the engine.
- Control integration slice implemented: durable local plan Markdown/compiled-plan records, Bonsai compiler dispatch through the application service, trusted project verifier argv, start-run request mapping, approval endpoint mapping, read-only diff/artifact access, loopback static UI serving, and explicit unsupported pause/cancel behavior. Application/API/UI focused tests: **13 passed**.
- Added `workestra`/`local-agent-control serve` loopback entrypoint, project creation through explicit verifier argv, and UI SSE alignment with the durable `/api/runs/{id}/events` stream. Control/API/CLI/Plan Intake/UI focused tests: **25 passed**; compileall passed.
- Full suite after the first control vertical slice: **238 passed** with `GIT_CONFIG_GLOBAL=/dev/null`; compileall and `git diff --check` passed.
- First disposable API-driven approval/resume E2E did not reach the approval state: the asynchronous start response was accepted, but polling never observed `WAITING_FOR_APPROVAL`. The temporary run was discarded; next step is to capture returned run states/error details before changing lifecycle code.
- Root cause confirmed: `ProjectRegistry` defaulted `runs/` inside the target workspace, so run creation made the repository dirty before the engine's clean-baseline check. Fixed control-owned default runs/analytics roots to live beside the registry (`.../runs/<project-id>` and `.../analytics/<project-id>`); explicit paths remain supported. Focused application/API tests: **11 passed**.
- The follow-up E2E reached `WAITING_FOR_APPROVAL` and created an isolated agent branch, then verification failed closed with the expected `missing_metadata` bootstrap code because the disposable target had neither locked metadata nor a reusable target tool. The fixture will use a target-owned `.venv/bin/pytest` reuse path; no bootstrap policy change is needed.
- Disposable API-driven control E2E passed with target-owned `.venv/bin/pytest` reuse: project creation, untrusted Markdown import, mocked compiler preview, asynchronous start after browser disconnect, approval SSE replay, approval grant, resume, trusted verification, and final `PASSED` state. Run `4f6c092dceeb`; target main stayed unchanged.
- Added safety regressions for loopback-only binding and explicit unsupported pause behavior; Control/API/Plan Intake/UI focused tests: **23 passed**.
- Full suite after Control API/application/UI integration and safety regressions: **240 passed** with `GIT_CONFIG_GLOBAL=/dev/null`; compileall and `git diff --check` passed.
- Added plan-record path containment so a tampered local control index cannot make the compiler read Markdown outside its plan directory. Focused Control/API/Plan Intake/UI tests: **24 passed**.
- Real Bonsai Plan Compiler smoke failed closed: Bonsai ROCm startup/full offload/Flash Attention succeeded, but the model response was not JSON (`Invalid strict Plan v2 candidate ... Expecting value: line 1 column 1`). No plan was accepted, no workspace was touched, and the server cleaned up. This is the first demonstrated Plan Compiler model-output blocker; structured-output behavior needs investigation before claiming real Markdown-to-Plan success.
- Diagnosis: direct raw Bonsai calls with the same schema sometimes returned valid JSON and sometimes empty `content`; malformed non-empty output remains fail-closed. Added exactly one bounded retry for an empty compiler response, with focused Plan Intake tests **9 passed**.
- Removed a demonstrated false positive in compiler policy checking: assumptions/unresolved commentary containing words such as `deployment` no longer trigger executable-intent rejection; only the request/task text is policy-scanned, while unresolved questions still reject preview. Plan Intake focused tests: **10 passed**.
- Real Bonsai compiler follow-up: an explicit path/behavior Markdown request still returned empty content twice and failed with the same strict-candidate parse error after the one bounded retry. Raw direct calls can produce valid JSON, so this is an intermittent Bonsai/llama.cpp output-reliability limitation. The compiler remains fail-closed; no parser repair or unsafe fallback was added. M2 real-model compile acceptance remains open.
- Final deterministic validation after the control integration: **243 passed**, compileall passed for `src tests web`, `git diff --check` passed, and `uv run workestra --help` exposes `approve`, `resume`, and loopback `serve`.
- Fresh-environment check: `uv sync --locked` resolved/checked successfully without changing the lockfile.
- Changes view integration now derives a capped committed diff from the authoritative checkpoint commit in task metrics when no `.diff` artifact exists; commit IDs are strictly validated before the fixed Git read. Focused application/API/UI tests: **17 passed**.
- Full suite after diff/results integration: **244 passed** with isolated Git identity; compileall and `git diff --check` passed.
- Final disposable Control E2E after all integration changes passed again (`a7cf95aff387`): loopback API/UI route, durable plan import/preview, browser-disconnect-safe background start, approval SSE replay, approval grant/resume, trusted target verifier reuse, final task/run `passed`, and clean server shutdown.
- Final worktree verification: compileall and `git diff --check` passed; no `llama-server` process remains. No commit was created.

### 2026-09-21 — Bonsai Plan Compiler response diagnosis
- Re-read the Plan Intake, llama-server adapter, response schema, and focused tests before
  changing behavior. The installed ROCm llama.cpp build documents OpenAI-compatible
  `response_format.type=json_schema` and maps the nested `json_schema.schema` correctly; its
  reasoning protocol returns final text in `message.content` and private reasoning separately in
  `message.reasoning_content`.
- A live raw request using the current Bonsai config reproduced the empty-content failure: HTTP
  200 with `finish_reason=length`, `content_len=0`, and only `reasoning_content` (about 8.5k
  characters) after the 2,048-token budget. This is a reasoning-budget exhaustion, not a schema
  parser failure or alternate final-content field.
- In the same server process, `max_tokens=4096` produced schema-shaped final content, a per-request
  `reasoning_effort=low` override produced final content, and
  `chat_template_kwargs={"enable_thinking": false}` produced final content with no reasoning and
  the shortest latency. The current Plan Compiler sends neither per-request control and therefore
  can exhaust the budget under Bonsai `xhigh`.
- The llama-server adapter investigation removed the old optional raw-reasoning fallback and added
  focused tests ensuring `reasoning_content` is never treated as final output. Empty final content
  remains fail-closed; the implemented fix adds only bounded diagnostics/request controls, with no
  reasoning leakage or parser repair.
- Implemented the narrow reliability fix: `LlamaServer.chat` now forwards optional per-request
  reasoning/template controls, rejects empty or non-text assistant content with bounded metadata
  (`finish_reason`, message fields, and reasoning-presence only), and never returns private reasoning
  as a candidate. Plan Compiler retries that controlled empty response once and requests
  `chat_template_kwargs={"enable_thinking": false}` so Bonsai's global `xhigh` setting cannot consume
  the entire structured-output budget. Focused adapter/Plan Intake tests: **28 passed**.
- Added a regression for preserving the live empty-response diagnostics through the bounded retry;
  the focused adapter/Plan Intake set now passes **29 tests**.
- A five-request live raw probe using the exact current compiler request confirmed the old behavior
  deterministically: all five HTTP 200 responses took **42.755–43.123s**, had empty `content`,
  `finish_reason="length"`, `completion_tokens=2048`, and only `reasoning_content` (8.4–8.9k
  characters). Startup and cleanup were clean; no server remained. This rules out an intermittent
  alternate response field for the old request and confirms reasoning-budget exhaustion.
- Three real post-fix `compile_plan` trials with an explicit helper/test Markdown request all
  returned structured candidates in **8.5–16.2s** with no empty-content error. Each was safely
  rejected only because the model invented an unresolved edge-case question; this is distinct from
  response transport failure. The compiler prompt now says unresolved questions are for missing
  requirements that block safe implementation, not invented edge cases.
- Repeated real trials with explicit input-domain behavior then compiled successfully **3/3** in
  **6.2–6.4s** each. Every result was schema-valid, had the expected code and test tasks, and had
  no unresolved questions. This establishes a stable Markdown→Bonsai→Plan v2 path for a bounded
  request while preserving fail-closed rejection for genuinely unresolved requirements.
- Focused regressions now also assert that Plan Intake sends the active JSON schema together with
  the no-thinking request control; adapter/Plan Intake remains **29 passed**.
- Real Control API/UI lifecycle smoke with actual Bonsai compilation passed (`5d5ce7585114`):
  Markdown import → API compile in **5.99s** → generated high-risk test task → durable approval
  wait → SSE event replay → approval/resume → target-owned pytest success. The disposable target
  stayed isolated and the server shut down cleanly; finalization was stubbed only to keep this
  control-plane smoke focused on intake, approval, and trusted execution.
- Scoped strict empty-content diagnostics to Plan Intake via `require_content=True`; other model
  roles retain their existing empty-string handling while never consuming reasoning as final text.
  Focused Control/Plan Intake/llama-server/UI regressions passed: **47 tests**.
- Full isolated orchestrator suite passed: **255 tests** with `GIT_CONFIG_GLOBAL=/dev/null`.
- `compileall -q src tests benchmarks`, `git diff --check`, and the post-E2E process scan all
  passed; no model or control smoke process remains.
- Final post-validation real Control API/UI smoke also passed (`0045b35eee48`): actual Bonsai
  Markdown compilation in **6.02s**, generated approval-gated test task, approval/SSE/resume,
  target-isolated verification, and real retrospective finalization. The disposable server and
  model lifecycle cleaned up successfully.
- Final compileall, `git diff --check`, and process cleanup checks passed after the scoped adapter
  compatibility adjustment; the full-finalization E2E left no model/control process and no commit
  was created.

### 2026-09-21 — Workestra Control failure diagnosis
- Reproduced the target baseline failure without changing AI-Assistant: the existing scheduler test
  hardcodes `2026-09-15T07:30:00+03:00`, while the application lifespan recomputes the persisted
  schedule from the current date (`2026-09-21`). The verifier parses the same single pytest
  identity in baseline and post-change; this remains a pre-existing target failure and must stay
  fail-closed/authoritatively classified rather than being fixed in the target.
- Reproduced the Control contract bug: project serialization exposes `workspace_root`, while the
  UI reads `project.path`, rendering `undefined`.
- Reproduced the UI run-selection bug: asynchronous `POST /api/runs` returns `202 {status: accepted}`
  before the synchronous engine has created a run ID; the UI immediately calls `/runs/undefined`,
  which surfaces as a misleading Control service error. The fix must keep the accepted/background
  lifecycle and show durable run state after it exists.
- Focused baseline/Control/API/UI regressions after the narrow fixes passed: **24 tests**. The
  baseline triage behavior remains unchanged and still rejects uninterpretable or dirty baselines.
- Implemented the contract fixes: `Project.to_dict()` now includes a backward-compatible `path`
  alias while the UI prefers `workspace_root`; the UI no longer dereferences an absent async run
  ID; and `FileNotFoundError` maps to structured 404 instead of generic `Control service failed`.
  Existing uncommitted UI syntax/compiled-state changes were preserved.
- Expanded focused runtime/API/UI/verification coverage passed: **48 tests**, including dependency
  failure propagation (`FAILED` → dependent `BLOCKED`, unrelated `SKIPPED`).
- Full isolated suite passed: **260 tests** with `GIT_CONFIG_GLOBAL=/dev/null`.
- `compileall -q src tests benchmarks`, browser JavaScript syntax check, and `git diff --check`
  passed.
- Full disposable Control E2E passed (`a4dbefc5e6d8`): API project response exposed the real path,
  Markdown compiled with Bonsai, asynchronous run acceptance did not request an undefined run,
  approval/SSE/resume completed, target-owned verification passed, retrospective finalization
  completed, and all resources shut down cleanly.
- Final compileall, Node syntax, diff, and process-cleanup checks passed. No commit was created;
  AI-Assistant and production/VPS were untouched.
