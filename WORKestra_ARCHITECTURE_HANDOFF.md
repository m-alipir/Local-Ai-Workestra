# Workestra Architecture Handoff

Status: architecture direction with a partial 2026-09-23 implementation. The
full research loop and broad stack coverage are not implemented.

## Current assessment

Workestra's execution and safety layer is more mature than its planning and
project-definition layer. Preserve these foundations:

- isolated agent branches/workspaces and clean-target checks
- deterministic semantic-edit and Plan v2 validation
- trusted verifier execution, baseline triage, rollback, and checkpoints
- fail-closed review/security behavior
- durable run diagnostics, trajectory, metrics, and lifecycle state
- immutable compiled-plan revisions and run-to-revision binding
- bounded, sequential local-model execution and cleanup

The main architectural weakness is the path:

`Sol plan -> compiler -> project/bootstrap definition -> executable run`

The compiler now has a bounded ProjectSpec transition, but it remains the
largest architectural weakness and is not complete for every project class.

## Implemented transition

Plan Intake can emit and persist a strict ProjectSpec alongside the immutable
execution-plan revision. Deterministic resolution currently derives the
supported Python/FastAPI/SQLite/pytest capabilities and fixed FastAPI bootstrap
and verifier metadata. Node/TypeScript/frontend and Godot/GDScript intents are
recognized but stop with structured blocking research requirements because
they do not yet have trusted bootstrap/verifier profiles. Unbound greenfield
plans can use the safe default Workestra project directory and the existing
bounded bootstrap/registration path. Existing project binding, revision
checks, verifier ownership, and the execution/safety engine remain unchanged.

## Long-term target

The intended flow is:

`User describes project -> Sol produces high-level plan -> import -> Compile -> review -> Start -> working repository`

For a normal greenfield project, the user should not separately provide the
project name/slug, target folder, Git initialization, language/runtime setup,
dependency bootstrap, bootstrap profile, verifier argv, or test-environment
setup. Workestra should derive these from the plan, subject to deterministic
validation and explicit safety boundaries.

## Compiler redesign

Treat the compiler as a compiler from a high-level plan into a complete
executable project specification, not merely a task-order normalizer:

`Sol Plan -> Intent / ProjectSpec -> Capability Resolution -> Research if required -> Execution Plan -> Deterministic Validation`

Where applicable, the compiled specification should describe:

- project name and slug; new-project versus existing-project intent
- workspace location and target ownership
- language, framework/engine, and application/project type
- database/persistence choice
- package/tooling environment and trusted bootstrap requirements
- trusted verifier/test strategy
- task DAG, task/file boundaries, and completion criteria
- risk, approval, review, and security requirements

## Composable capabilities

Do not create one giant profile for every framework combination. Prefer
composable trusted capabilities such as:

`python`, `fastapi`, `sqlite`, `pytest`, `node`, `typescript`, `react`, `vite`, `godot`, `gdscript`

The compiler may select capabilities; deterministic Workestra code must resolve
them to fixed, bounded setup and verifier behavior. Models must never gain
arbitrary shell or dependency-install authority. For example, a FastAPI +
SQLite API should resolve to capabilities such as `python + fastapi + sqlite +
api-testing`, then to trusted Workestra setup and verification rules.

## Research loop

The compiler must distinguish:

- **KNOWN** — covered by a trusted Workestra capability or rule
- **DERIVABLE** — reliably inferable from the Sol plan
- **UNKNOWN** — current or specialized information that must be researched

For UNKNOWN items, emit a structured research request for Sol or a research
agent instead of guessing. Compilation resumes after research returns. This is
important for current framework/tool versions, Godot/Steam/networking
integrations, unfamiliar libraries, platform-specific requirements, and
specialized build/test strategies. The compiler coordinates research; it does
not become an unrestricted general research agent.

## Model abstraction

Keep model names out of architecture where practical. Use replaceable roles:

- planner
- plan compiler
- primary coder
- diagnostic/security reviewer
- fallback coder

Sol, Bonsai, Qwen, GPT-OSS, and Devstral are implementations/configuration,
not architectural contracts.

## State architecture follow-up

Several previous bugs involved stale or contradictory state between the UI, run
state, tasks, SSE, retrospective, and diagnostics. Long term, move toward one
canonical run lifecycle/event source from which UI, state, and retrospective
views are derived. Candidate events include:

`task_started`, `model_started`, `edit_applied`, `verification_failed`,
`rollback_started`, `rollback_completed`, `task_passed`, `review_passed`, and
`run_completed`.

Do not implement full event sourcing as part of this handoff; record it as a
future architecture milestone.

## Roadmap

1. Compiler / `ProjectSpec` / capability architecture (partial; broaden safely)
2. Greenfield lifecycle: plan -> automatic project creation/bootstrap (Python partial)
3. Planner/compiler research feedback loop
4. Canonical run event/state model
5. Bounded Sol/Codex <-> Workestra MCP/tool bridge
6. Broader real-project classes and larger E2E workloads

Do not rewrite the existing execution engine, Git isolation, verifier,
rollback/checkpoint, or safety system without a concrete demonstrated reason.
Those are currently the stronger parts of the architecture. The largest
justified redesign area is the compiler/project-definition layer.
