from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "web"


def test_control_ui_is_static_and_uses_control_api() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Workestra Control" in html
    assert 'request("/plans/import"' in javascript
    assert "/api/runs" in javascript
    assert "EventSource" in javascript
    assert "shell" not in javascript.lower()


def test_control_ui_does_not_render_raw_event_html() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "innerHTML" not in javascript
    assert "textContent" in javascript
