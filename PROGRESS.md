# Workestra Project State

## Goal

Make Workestra a safe, local-first system that can take a high-level project
plan through compilation, review, isolated implementation, verification, and
checkpointed delivery to a working repository.

The current milestone is to make the compiler/project-definition boundary
reliable for greenfield projects while preserving the stronger execution and
safety core. Production deployment, VPS changes, and unrestricted model or
shell authority are out of scope.

## Current State

- The latest verified isolated baseline is **350 passed** from
  `GIT_CONFIG_GLOBAL=/dev/null uv run pytest -q` on 2026-09-23.
- The latest recorded checks also pass: `uv run python -m compileall -q src
  tests benchmarks`, `node --check web/app.js`, and `git diff --check`.
- The latest meaningful Local Bookmarks E2E, `414f7cf4d21e`, failed closed on
  a compiler/model task-boundary mismatch. Task 003 declared `app/api/`, while
  the model needed to edit `app/main.py` and `app/bookmarks.py`; those edits
  were rejected and rolled back. Task 005 did not produce passing API tests
  within its retry budget. The target was not manually repaired.
- Fresh unbound Local Bookmarks imports previously failed before ProjectSpec
  and revision persistence when the model omitted verifier dependencies. The
  compiler now derives full-suite dependencies from preceding code tasks and
  uses file/scope evidence for narrower verifiers; genuinely ambiguous
  relationships still fail closed.
- The earlier operational greenfield run `903977a81d5f` proved automatic
  target creation, trusted bootstrap, six-task execution, checkpoints, and
  finalization. It is not accepted as semantic completion because a retry for
  a test task changed source code while leaving only a smoke test.
- Workestra Control provides loopback HTTP/SSE APIs, durable project/plan/run
  records, revision-aware compile/start behavior, diagnostics, history, and a
  dependency-free static UI. The existing execution engine remains the
  execution authority.
- ProjectSpec and composable capability resolution are partially implemented.
  Python/FastAPI/SQLite/SQLAlchemy/pytest/API-testing are supported through
  deterministic trusted setup. Node/TypeScript/React/Vite and Godot/GDScript
  are recognized but currently produce blocking research requirements.
- Greenfield Python/FastAPI projects can be created and bootstrapped from an
  unbound plan. Trusted setup uses bounded `uv` behavior and the fixed verifier
  `uv run pytest -q`; the FastAPI profile includes bounded `httpx` and, where
  required, SQLAlchemy dependencies.
- Task execution now classifies changes as primary, discouraged/grey, or
  forbidden. Grey changes receive focused semantic review; forbidden changes
  remain hard failures with rollback.
- Scope review decisions are structured as `PASS`, `REVISE`, `RETRY_FRESH`, or
  `FAIL_HARD`. A revision preserves the current attempt and is capped at two
  repairs before a fresh retry; safety failures skip repair and fallback.
- Active local model routing is sequential through `LlamaServer`: Qwen Coder
  is the primary explorer/coder, Devstral is the fallback coder, GPT-OSS is
  the diagnostic/security reviewer, and Bonsai 2 is used for plan compilation,
  deeper reasoning, and retrospective generation. These are replaceable role
  implementations, not architectural contracts.
- The primary checkout is `main` at `f8e8ac9` with substantial uncommitted
  stabilization, Control, and compiler work. Preserve the dirty worktree;
  no commit or push has been made for the current work.

## Active Work / Next

- [ ] Run a fresh Local Bookmarks E2E after the scope/compiler changes and require
  semantic completion, not merely a passing smoke verifier.
- [ ] Change compiler output from narrow exact-file predictions to coarse
  semantic/directory scopes that guide review and execution.
- [ ] Strengthen completion criteria so generated tests and requested behavior
  cannot be bypassed by a source-only retry or an underspecified verifier.
- [ ] Design the structured planner/compiler research feedback loop. This is
  planned, not implemented; current unknowns are persisted as blockers.
- [ ] Add trusted capability profiles incrementally for additional project
  classes only when their bootstrap and verifier behavior can remain bounded.
- [ ] Plan, but do not yet implement, a canonical run lifecycle/event source
  for UI state, diagnostics, retrospective views, and durable run state.

## Known Issues / Limitations

- Compiler task scopes are still partially derived from narrow existing plan
  data; legitimate integration edits now go through grey review, but this can
  consume bounded repair/fresh-retry capacity until compiler scopes are made
  coarse.
- A trusted verifier can still be weaker than the full task intent; semantic
  completion needs stronger compiler boundaries and completion criteria.
- Scope repair is bounded to two Qwen-side revisions. A non-PASS scope decision
  after the fallback coder rolls back the attempt; fallback scope repair is not
  yet a separate loop.
- The research loop does not yet send structured unknowns to Sol or another
  research agent and resume compilation after answers.
- Node/TypeScript/frontend and Godot/GDScript have no trusted bootstrap/verifier
  profiles yet. Workestra must fail closed for these rather than guess setup.
- The active environment does not provide Ruff, so validation currently relies
  on pytest, compileall, Node syntax checks, and Git diff checks.

## Architecture / Decisions

- Preserve isolated Git branches/workspaces, clean-target checks, execution
  leases, checkpoints, rollback, verifier logic, security/review stages,
  diagnostics, and bounded local-model execution.
- All model edits use strict semantic operations, authoritative path/file
  scopes, exact matching, traversal checks, and Git preflight. Primary scopes
  guide review; discouraged scopes are not automatic failures; forbidden paths
  fail closed. Rejected or failed edits remain controlled failures.
- Unexpected task changes are reviewed only as a focused diff. `REVISE` repairs
  the current attempt with structured preserve/remove guidance; after two
  repairs the bounded fresh-retry policy applies.
- Verification is baseline-aware and fails closed for unknown or
  uninterpretable results. Pre-existing failures may remain only when their
  structured identities are unchanged.
- Trusted bootstrap and verifier commands come from deterministic Workestra
  capability resolution. Plans and models cannot supply arbitrary shell,
  dependency-install, deployment, remote-access, or verifier authority.
- Imported Markdown and model output are untrusted. Plan verification fields
  are informational; only the trusted global test command is executable.
- Compiled plans are immutable revisions with source/plan digests. A run binds
  to the exact revision and rejects stale start requests.
- Fresh and resumed execution share lease, rollback, finalization, and
  terminal-state rules. Terminal state is published only after finalization
  and model cleanup complete.
- Control reads authoritative run artifacts/state and protects against stale
  asynchronous responses, mismatched project/run scopes, and SSE replay
  leakage. Pause/cancel remain unsupported until safe interruption exists.
- Keep model roles replaceable. Specific names such as Sol, Bonsai, Qwen,
  GPT-OSS, and Devstral must not become architectural dependencies.
- The main redesign target is the compiler/project-definition layer. Do not
  rewrite the executor, Git isolation, verifier, rollback/checkpoint, or safety
  system without a concrete demonstrated reason.

## Completed Milestones

- [x] Isolated agent branches/workspaces, clean baselines, leases, checkpoints,
  rollback, and fail-closed lifecycle handling.
- [x] Deterministic semantic edit protocol, path grounding, task boundaries,
  strict Git validation, and baseline-aware verification.
- [x] Plan v2 graph validation, topological execution, dependency blocking,
  approval policy, trusted test/review tasks, and resume behavior.
- [x] Immutable compiled-plan revisions, digests, exact run binding, and
  fresh/resumed finalization parity.
- [x] Durable run state, metrics, trajectory, retrospective authority labels,
  diagnostics, Control API/SSE, history management, and race protection.
- [x] Bounded sequential local model routing with cleanup and fail-closed
  security/reviewer boundaries.
- [x] Trusted Python/FastAPI greenfield bootstrap with SQLite/SQLAlchemy,
  pytest, API-testing, and bounded `httpx` support.
- [x] Three-level task scopes, focused grey-scope review, bounded revise/fresh
  retry recovery, and hard forbidden-path rollback behavior.
- [x] Partial ProjectSpec and composable capability compiler boundary,
  including structured blocking research requirements.
- [x] Disposable Control and operational greenfield E2Es covering compilation,
  bootstrap, approval/resume, verification, checkpoints, and finalization.

## Useful Commands

From the repository root:

```sh
uv sync --locked
GIT_CONFIG_GLOBAL=/dev/null uv run pytest -q
uv run python -m compileall -q src tests benchmarks
node --check web/app.js
git diff --check
uv run workestra --help
uv run local-agent-control --help
```

Before changing code, inspect the preserved worktree and recent history:

```sh
git status --short --branch
git log --oneline --decorate -10
```

For a local Control server, use a loopback bind and a registry outside the
target workspace, following the command examples in `README.md`.
