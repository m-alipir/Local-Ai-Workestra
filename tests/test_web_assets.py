from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "web"


def test_control_ui_is_static_and_uses_control_api() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Workestra Control" in html
    assert 'id="build-version"' in html
    assert 'response?.version ? `Build ${response.version}`' in javascript
    assert "plan-history" in html
    assert "diagnostics" in html
    assert "<details" in html
    assert "edit-project" in html
    assert "delete-project" in html
    assert "archive-run" in html
    assert "cleanup-run" in html
    assert "Plans and history persist" in html
    assert 'request("/plans/import"' in javascript
    assert "/api/runs" in javascript
    assert 'request("/plan-history")' in javascript
    assert "state.planGroups" in javascript
    assert "latest_good?.plan_id" in javascript
    assert "SELECTED_SOURCE_STORAGE_KEY" in javascript
    assert "/diagnostics" in javascript
    assert "EventSource" in javascript
    assert "localStorage" in javascript
    assert "project_id=" in javascript
    assert "project.workspace_root" in javascript
    assert "No projects available" in javascript
    assert "syncRunActions" in javascript
    assert '["passed", "failed", "skipped"]' in javascript
    assert "Array.isArray(response.data || response)" in javascript
    assert "const runId = run.run_id || run.id;" in javascript
    assert "if (runId)" in javascript
    assert "error-details" in javascript
    assert "selectedRunToken" in javascript
    assert "clearRunDetail" in javascript
    assert "refreshRuns(token)" in javascript
    assert "state.eventSource !== source" in javascript
    assert "payload?.run_id" in javascript
    assert "project-edit-form" in javascript
    assert 'data-mode="edit"' in html
    assert 'data-mode="create"' in html
    assert 'id="project-edit-name" required' not in html
    assert 'id="project-edit-path" required' not in html
    assert "projectEditMode" in javascript
    assert "projectEditOriginal" in javascript
    assert "projectEditValues" in javascript
    assert "projectEditPayload" in javascript
    assert "Object.fromEntries" in javascript
    assert 'method: "PATCH"' in javascript
    assert 'method: "DELETE"' in javascript
    assert "window.confirm" in javascript
    assert 'manageRun("archive"' in javascript
    assert 'manageRun("cleanup"' in javascript
    assert 'status === "waiting_for_approval"' in javascript
    assert '$("pause-run").disabled = true' in javascript
    assert '$("cancel-run").disabled = true' in javascript
    assert "shell" not in javascript.lower()


def test_control_ui_separates_greenfield_and_existing_project_flows() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Register existing repository" in html
    assert "Existing project registration" in html
    assert "Verifier argv" not in html
    assert 'id="create-project"' in html
    assert 'id="project-eligibility"' in html
    assert 'id="recompile-plan"' in html
    assert 'compilePlan(state.planId)' in javascript
    assert "projectCreationEligible" in javascript
    assert '$("create-project").disabled = !current || !needsCreation || !state.projectCreationEligible' in javascript
    assert '$("start-run").disabled = !current || (needsCreation ? !state.projectCreationEligible : !startableProject)' in javascript
    assert "/eligibility?compiled_revision=" in javascript
    assert 'method: "POST"' in javascript and 'createProjectForPlan(planId, revision)' in javascript
    assert '$("start-run").textContent = needsCreation ? "Create & Start" : "Start"' in javascript
    assert 'await createProjectForPlan(planId, revision)' in javascript
    assert 'project_id: projectId' in javascript
    start_handler = javascript.split('$("start-run").onclick = async () => {', 1)[1]
    assert start_handler.index('await createProjectForPlan(planId, revision)') < start_handler.index('request("/runs"')
    assert 'const needsCreation = greenfield && !state.compiledPlanProjectId' in javascript
    assert 'const correctGreenfieldProject = greenfield && project?.id === state.compiledPlanProjectId' in javascript
    assert 'const correctBoundProject = project?.id === state.compiledPlanProjectId' in javascript
    assert 'const startableProject = state.compiledPlanProjectId ? correctBoundProject : Boolean(project)' in javascript
    assert "Rejected: ${(plan.unresolved_issues || []).join" in javascript
    assert 'state.projectId = $("project-select").value || null' in javascript
    assert 'project?.id === state.compiledPlanProjectId' in javascript
    assert "Workestra-managed trusted verifier" in html
    assert "projectSpec.bootstrap_profile" in javascript
    assert "projectSpec.workspace_root" in javascript
    assert "projectSpec.capabilities" in javascript


def test_greenfield_primary_action_explains_creation_and_start() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="start-plan-hint"' in html
    assert 'aria-describedby="start-plan-hint"' in html
    assert "This compiled greenfield plan will create its trusted workspace and start the run." in javascript
    assert "Create &amp; Start" in html
    assert "Create Project first" not in javascript


def test_control_ui_does_not_render_raw_event_html() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "innerHTML" not in javascript
    assert "textContent" in javascript


def test_control_ui_only_shows_terminal_failure_diagnostics() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'run.status === "failed" &&' in javascript
    assert 'clearDiagnostics();' in javascript


def test_control_ui_has_accessible_cherry_workspace_and_safe_renderers() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert 'id="add-project"' in html
    assert 'id="run-list"' in html and 'aria-live="polite"' in html
    assert 'id="run-list" class="list" role="list"' not in html
    assert 'id="task-list"' in html and 'role="list"' in html
    assert 'data-status="checking"' in html
    assert "--canvas: #0d0a0b" in css
    assert "grid-template-columns: repeat(12" in css
    assert ".project-card { grid-column: span 4; }" in css
    assert ".plan-card { grid-column: span 8; }" in css
    assert "renderPlanPreview" in javascript
    assert "renderRunList" in javascript
    assert "renderTask" in javascript
    assert 'setAttribute("aria-current"' in javascript
    assert 'request("/health")' in javascript
    assert 'setStatus("health"' in javascript
    assert 'className = "raw-fallback"' in javascript
    assert '[hidden] { display: none !important; }' in css
    assert "--subtle: #9b858d" in css
    assert "currentTaskId" in javascript
    assert '"Approve & resume"' in javascript
    assert "/approvals/" in javascript and "/resume" in javascript
    assert 'body: JSON.stringify({ project_id: projectId })' in javascript
    assert "lastEventId" in javascript
    assert "last_event_id" in javascript
    assert "eventsQuery" in javascript
    assert 'dot.dataset.status = status' in javascript


def test_control_ui_has_desktop_workbench_and_safe_failed_history_removal() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-workbench-tab="plan"' in html
    assert 'data-workbench-tab="run"' in html
    assert 'data-workbench-tab="history"' in html
    assert 'id="history-list"' in html
    assert 'id="plan-history-panel"' in html
    assert 'Raw logs · closed by default' in html
    assert 'Expandable evidence drawer' in html
    assert 'compact diagnostic archive' in html
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr))' in css
    assert 'renderRunList(items, "history-list")' in javascript
    assert 'Only failed runs can be removed from normal history.' in javascript
    assert 'diagnostic archive will be kept in .archive' in javascript


def test_control_ui_guards_compile_and_run_refresh_races() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="plan-revision"' in html
    assert 'id="active-run-duration"' in html
    assert "compiledPlanRevision" in javascript
    assert "Recompile required" in javascript
    assert "compileGeneration" in javascript
    assert "planLoadGeneration" in javascript
    assert "runRefreshGeneration" in javascript
    assert "refreshRunDetail" in javascript
    assert 'body: JSON.stringify({ force: true })' in javascript
    assert "setInterval(updateActiveRunDuration, 1000)" in javascript
    assert "compiled_revision" in javascript
    assert "run?.updated_at" in javascript


def test_recompile_failure_keeps_last_good_preview_and_use_plan_source() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    compile_handler = javascript.split("async function compilePlan(planId) {", 1)[1].split("\nfunction connectEvents", 1)[0]
    reuse_handler = javascript.split("async function reusePlan(", 1)[1].split("\nasync function compilePlan", 1)[0]

    assert "state.compiledPlanId = null" not in compile_handler
    assert 'renderPlanPreview(saved)' in compile_handler
    assert "latest compile failed" in javascript
    assert '$("plan-markdown").value = plan.markdown || record.markdown || ""' in reuse_handler


def test_source_history_is_not_gated_by_active_project_and_hydrates_bound_project() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert 'request("/plans")' in javascript
    assert 'request("/plans?project_id=' not in javascript
    assert 'state.projectId = null;' in javascript
    assert 'const project = state.projects.find((item) => item.id === state.compiledPlanProjectId)' in javascript
    assert 'renderPlanHistoryDetails(group)' in javascript
    assert 'Inspect compile attempts and revisions' in javascript
    selection_handler = javascript.split('$("project-select").onchange = () => {', 1)[1].split("\n};", 1)[0]
    assert "state.planId = null" not in selection_handler
    assert "refreshRuns().catch(showError)" in selection_handler
