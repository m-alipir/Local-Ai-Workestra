from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

from local_agent_orchestrator.control_api import (
    ControlAPI,
    create_server,
)


class FakeService:
    def __init__(self, runs_dir):
        self.runs_dir = runs_dir
        self.started = threading.Event()
        self.start_payload = None

    def list_projects(self):
        return []

    def start_run(self, payload):
        self.start_payload = payload
        self.started.set()


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection(*server.server_address)
    encoded = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if encoded is not None:
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, encoded, request_headers)
    response = connection.getresponse()
    content = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), content


def test_health_and_loopback_default(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        status, _, content = request(server, "GET", "/api/health")
        assert status == 200
        assert json.loads(content) == {"status": "ok"}
    finally:
        server.server_close()


def test_non_loopback_binding_is_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        create_server(runs_dir=tmp_path / "runs", host="0.0.0.0", port=0)


def test_root_serves_static_control_ui(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, content = request(server, "GET", "/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b"Workestra Control" in content
    finally:
        server.shutdown()
        server.server_close()


def test_event_replay_honours_last_event_id(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"event": "one", "run_id": "run-1", "task_id": "t1"})
        + "\n"
        + json.dumps({"event": "two", "run_id": "run-1", "task_id": "t1"})
        + "\n",
        encoding="utf-8",
    )
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, content = request(
            server,
            "GET",
            "/api/runs/run-1/events",
            headers={"Last-Event-ID": "1"},
        )
        assert status == 200
        assert headers["Content-Type"] == "text/event-stream"
        assert b"id: 2" in content
        assert b'"event": "two"' in content
        assert b'"event": "one"' not in content
    finally:
        server.server_close()


def test_malformed_and_untrusted_requests_are_rejected(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = request(
            server,
            "POST",
            "/api/runs",
            body={"command": "rm -rf /"},
        )
        assert status == 400

        status, _, _ = request(
            server,
            "GET",
            "/api/runs/../etc/passwd/events",
        )
        assert status in {400, 404}

        status, _, _ = request(
            server,
            "GET",
            "/api/runs/run-1/events",
            headers={"Last-Event-ID": "bad"},
        )
        assert status == 400
    finally:
        server.server_close()


def test_start_delegates_to_service_without_engine_copy(tmp_path):
    service = FakeService(tmp_path / "runs")
    server = create_server(service=service, runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = request(
            server,
            "POST",
            "/api/runs",
            body={"plan_id": "plan-1"},
        )
        assert status == 202
        assert service.started.wait(1)
        assert service.start_payload == {"plan_id": "plan-1"}
    finally:
        server.shutdown()
        server.server_close()


def test_unsupported_pause_is_not_reported_as_success(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, content = request(server, "POST", "/api/runs/run-1/pause", {})
        assert status == 501
        assert b"UNSUPPORTED" in content
    finally:
        server.shutdown()
        server.server_close()
