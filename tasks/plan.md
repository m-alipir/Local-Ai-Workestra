# Implementation Plan: Compiler Project Specification

## Scope

Turn imported high-level Markdown into a validated compiled project
specification plus the existing executable Plan v2, while keeping all setup and
verification actions deterministic and trusted.

## Architecture decisions

- Keep `ExecutionPlan` as the task-DAG execution contract.
- Add a separate `ProjectSpec` contract for project identity, intent, stack,
  capabilities, research requirements, and trusted verifier/bootstrap profile.
- Treat model-produced project metadata as untrusted candidate data; validate it
  before persistence or bootstrap.
- Resolve only a small allowlisted set of composable capabilities. Unknown
  capabilities become structured research requirements, never shell commands.
- Preserve the existing project registry/bootstrap and execution engine APIs;
  greenfield integration is opt-in and bounded.

## Ordered tasks

1. Add ProjectSpec/capability/research models and deterministic validation.
2. Extend Plan Intake's strict candidate schema and compiler prompt to emit the
   project specification; derive safe defaults where unambiguous.
3. Persist compiled ProjectSpec with immutable plan revisions and expose it in
   Control compile/plan views.
4. Integrate supported greenfield specs with the existing bounded bootstrap and
   project registration path; reject unsupported or ambiguous setup fail-closed.
5. Add focused Python/FastAPI, Node/TypeScript/frontend, and Godot fixtures plus
   research-required and safety-boundary regressions.
6. Audit the complete import -> compile -> spec -> capability -> bootstrap ->
   start flow, simplify concrete duplication, and run full validation.

## Checkpoints

- After tasks 1–2: model/schema/derivation tests pass; no runtime integration.
- After task 3: persisted revision and Control restart tests pass.
- After task 4: greenfield bootstrap remains bounded; existing-project paths
  remain unchanged.
- Completion: focused tests, full pytest, compileall, browser syntax, diff
  hygiene, process cleanup, and fixture cleanup pass.

## Deferred

- Full autonomous research execution.
- Arbitrary framework support or one-profile-per-framework matrices.
- Full event sourcing/canonical lifecycle migration.
- MCP/tool bridge implementation.

## Greenfield reliability follow-up

1. Serialize model ownership across Workestra processes, record owned llama
   children, reap only verified stale children, and report unowned active models
   as temporary busy.
2. Store compile attempts separately from the last successful immutable
   revision; retain and rehydrate that revision after a failed recompile.
3. Resolve greenfield workspaces from a trusted configurable `projects_root`
   (default `~/Projeler`), not the Workestra config directory.
4. Add focused regressions for process ownership, prior-revision recovery,
   Use Plan, project-root safety, and repeated create/start.

## History, selection, and workspace collision follow-up

1. Identify Local Bookmarks E2E plans, projects, runs, and workspaces from
   source content, registry bindings, and Git history; archive only confirmed
   generated test artifacts and remove their active registrations.
2. Present compile attempts and immutable revisions under one source-plan
   identity; make Reuse Plan restore source, latest valid revision, ProjectSpec,
   binding, and action eligibility.
3. Resolve collision-free greenfield paths using `projects_root` and canonical
   registered paths; keep ProjectSpec immutable and fail closed on races.
4. Add backend/UI/cleanup regressions, restart Workestra from this tree, and
   run one clean browser E2E against that process.
