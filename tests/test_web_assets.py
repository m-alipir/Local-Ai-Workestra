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
