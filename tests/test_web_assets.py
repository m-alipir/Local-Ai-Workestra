from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "web"


def test_control_ui_is_static_and_uses_control_api() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Workestra Control" in html
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
    assert "/plans?project_id=" in javascript
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
