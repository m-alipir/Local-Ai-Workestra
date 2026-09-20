from __future__ import annotations

import json
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit


MAX_BODY_BYTES = 1_048_576
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
_FORBIDDEN_KEYS = {
    "cmd",
    "command",
    "exec",
    "executable",
    "shell",
    "shell_command",
    "test_command",
    "verifier",
    "verify_command",
}


class ControlService(Protocol):
    """Application-service boundary used by the HTTP layer.

    Lifecycle methods own orchestration. The API only validates requests,
    dispatches those methods, and serializes their returned state.
    """

    def list_projects(self) -> Any: ...

    def list_runs(self, **filters: Any) -> Any: ...

    def get_run(self, run_id: str) -> Any: ...

    def read_events(self, run_id: str, after_id: int = 0) -> Any: ...

    def read_artifacts(self, run_id: str) -> Any: ...


class FilesystemControlService:
    """Read-only adapter for existing run artifacts.

    Mutating operations intentionally remain application-service concerns.
    """

    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)

    def list_projects(self) -> list[dict[str, Any]]:
        return []

    def list_runs(self, **_: Any) -> list[dict[str, Any]]:
        return [
            self.get_run(path.name)
            for path in sorted(self.runs_dir.iterdir())
            if path.is_dir() and (path / "state.json").is_file()
        ] if self.runs_dir.is_dir() else []

    def get_run(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id) / "state.json"
        if not path.is_file():
            raise LookupError(f"Run not found: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def read_events(self, run_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        path = self._run_path(run_id) / "trajectory.jsonl"
        if not path.is_file():
            if not self._run_path(run_id).is_dir():
                raise LookupError(f"Run not found: {run_id}")
            return []
        events = []
        for event_id, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if event_id <= after_id or not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                event = dict(event)
                event.setdefault("id", event_id)
                events.append(event)
        return events

    def read_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        root = self._run_path(run_id)
        if not root.is_dir():
            raise LookupError(f"Run not found: {run_id}")
        return [
            {"name": path.relative_to(root).as_posix(), "size": path.stat().st_size}
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]

    def _run_path(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("Invalid run id")
        return self.runs_dir / run_id


class ControlAPI:
    def __init__(
        self,
        service: ControlService | Any | None = None,
        *,
        runs_dir: str | Path = "runs",
        max_workers: int = 4,
    ) -> None:
        self.service = service or FilesystemControlService(runs_dir)
        self._jobs = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="control-run")

    def close(self) -> None:
        self._jobs.shutdown(wait=False, cancel_futures=False)

    def handle(self, method: str, target: str, headers: dict[str, str], body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
        try:
            method = method.upper()
            path, query = self._path(target)
            if method == "GET" and (not path or path[:1] == ("web",)):
                return self._static(path)
            if method == "GET" and path == ("api", "health"):
                return self._json(HTTPStatus.OK, {"status": "ok"})
            if method == "GET" and path == ("api", "projects"):
                return self._json(HTTPStatus.OK, self._call("list_projects"))
            if method == "GET" and len(path) == 3 and path[:2] == ("api", "projects"):
                return self._json(HTTPStatus.OK, self._call("get_project", path[2]))
            if method == "GET" and len(path) == 3 and path[:2] == ("api", "plans"):
                return self._json(HTTPStatus.OK, self._call("get_plan", path[2]))
            if method == "GET" and path == ("api", "runs"):
                return self._json(HTTPStatus.OK, self._call("list_runs", **query))
            if method == "GET" and len(path) == 3 and path[:2] == ("api", "runs"):
                return self._json(HTTPStatus.OK, self._call("get_run", path[2]))
            if method == "GET" and len(path) == 4 and path[:3] == ("api", "runs", path[2]) and path[3] == "artifacts":
                return self._json(HTTPStatus.OK, self._call("read_artifacts", path[2]))
            if method == "GET" and len(path) == 4 and path[:3] == ("api", "runs", path[2]) and path[3] == "diff":
                return self._json(HTTPStatus.OK, self._call("read_diff", path[2]))
            if method == "GET" and len(path) == 4 and path[:3] == ("api", "runs", path[2]) and path[3] == "events":
                return self._events(path[2], headers, query)

            payload = self._payload(body) if method == "POST" else None
            if method == "POST" and path == ("api", "projects"):
                return self._json(HTTPStatus.CREATED, self._call("create_project_request", payload))
            if method == "POST" and path == ("api", "plans", "import"):
                return self._json(HTTPStatus.CREATED, self._call("import_plan", payload))
            if method == "POST" and len(path) == 4 and path[:2] == ("api", "plans") and path[3] == "compile":
                return self._json(HTTPStatus.OK, self._call("compile_plan", path[2], payload))
            if method == "POST" and path == ("api", "runs"):
                return self._submit("start_run", payload)
            if method == "POST" and len(path) == 6 and path[:4] == ("api", "runs", path[2], "approvals") and path[5] in {"approve", "reject"}:
                action = "approve_run" if path[5] == "approve" else "reject_run"
                if action == "reject_run":
                    raise RuntimeError("Approval rejection is not supported by the execution engine.")
                approval_payload = payload or {}
                return self._json(
                    HTTPStatus.OK,
                    self._call(
                        action,
                        path[2],
                        project_id=approval_payload.get("project_id"),
                        task_id=path[4],
                    ),
                )
            if method == "POST" and len(path) == 4 and path[:2] == ("api", "runs"):
                return self._lifecycle(path[2], path[3], payload)
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", str(exc))
        except FileNotFoundError as exc:
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", str(exc))
        except LookupError as exc:
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", str(exc))
        except AttributeError as exc:
            return self._error(HTTPStatus.NOT_IMPLEMENTED, "UNSUPPORTED", str(exc))
        except RuntimeError as exc:
            return self._error(HTTPStatus.CONFLICT, "OPERATION_REJECTED", str(exc))
        except Exception:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Control service failed")

    def _path(self, target: str) -> tuple[tuple[str, ...], dict[str, str]]:
        parsed = urlsplit(target)
        raw = parsed.path
        if "\\" in raw or any(part in {".", ".."} for part in raw.split("/")):
            raise ValueError("Unsafe path")
        path = tuple(part for part in raw.split("/") if part)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
        return path, query

    def _payload(self, body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        self._reject_forbidden(value)
        return value

    def _reject_forbidden(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key).lower() in _FORBIDDEN_KEYS:
                    raise ValueError(f"Unsupported request field: {key}")
                self._reject_forbidden(nested)
        elif isinstance(value, list):
            for nested in value:
                self._reject_forbidden(nested)

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.service, name, None)
        if method is None:
            raise AttributeError(f"Application service does not implement {name}")
        return _jsonable(method(*args, **kwargs))

    def _submit(self, name: str, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        request_method = getattr(self.service, f"{name}_request", None)
        method = request_method or getattr(self.service, name, None)
        if method is None:
            raise AttributeError(f"Application service does not implement {name}")
        self._jobs.submit(method, payload)
        response = {"status": "accepted"}
        if payload.get("run_id") is not None:
            response["run_id"] = payload["run_id"]
        return self._json(HTTPStatus.ACCEPTED, response)

    def _lifecycle(self, run_id: str, action: str, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        names = {
            "pause": ("pause_run",),
            "resume": ("resume_run",),
            "cancel": ("cancel_run",),
            "approvals": (),
        }
        if action in {"pause", "resume", "cancel"}:
            method = next((getattr(self.service, name, None) for name in names[action]), None)
            if method is None:
                raise AttributeError(f"Application service does not implement {action}_run")
            self._jobs.submit(method, run_id)
            return self._json(HTTPStatus.ACCEPTED, {"status": "accepted", "run_id": run_id})
        if action == "approvals":
            raise ValueError("Approval endpoint requires approval id")
        return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")

    def _events(self, run_id: str, headers: dict[str, str], query: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        raw_id = next(
            (value for key, value in headers.items() if key.lower() == "last-event-id"),
            query.get("last_event_id", "0"),
        )
        try:
            after_id = int(raw_id)
        except ValueError as exc:
            raise ValueError("Last-Event-ID must be an integer") from exc
        if after_id < 0:
            raise ValueError("Last-Event-ID must be non-negative")
        events = self._call("read_events", run_id, after_id)
        if not isinstance(events, list):
            raise ValueError("Application service returned invalid events")
        chunks = []
        for index, event in enumerate(events, after_id + 1):
            if not isinstance(event, dict):
                continue
            event_id = event.get("id", index)
            name = str(event.get("event", "message"))
            data = json.dumps(event, ensure_ascii=False)
            chunks.append(f"id: {event_id}\nevent: {name}\ndata: {data}\n\n")
        return 200, {"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}, "".join(chunks).encode()

    def _json(self, status: int | HTTPStatus, value: Any) -> tuple[int, dict[str, str], bytes]:
        return int(status), {"Content-Type": "application/json"}, json.dumps(_jsonable(value), ensure_ascii=False).encode()

    def _error(self, status: int | HTTPStatus, code: str, message: str) -> tuple[int, dict[str, str], bytes]:
        return self._json(status, {"error": {"code": code, "message": message}})

    def _static(self, path: tuple[str, ...]) -> tuple[int, dict[str, str], bytes]:
        name = "index.html" if not path else "/".join(path[1:])
        candidate = (WEB_ROOT / name).resolve()
        if not candidate.is_file() or not _inside(candidate, WEB_ROOT):
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Asset not found")
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return 200, {"Content-Type": content_type}, candidate.read_bytes()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


class _Handler(BaseHTTPRequestHandler):
    server: "ControlHTTPServer"

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_BODY_BYTES:
            self._write(*self.server.api._error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", "Invalid request body size"))
            return
        body = self.rfile.read(size) if size else b""
        headers = {key: value for key, value in self.headers.items()}
        self._write(*self.server.api.handle(method, self.path, headers, body))

    def _write(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_: Any) -> None:
        return


class ControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], api: ControlAPI) -> None:
        self.api = api
        super().__init__(address, _Handler)

    def server_close(self) -> None:
        self.api.close()
        super().server_close()


def create_server(
    service: ControlService | Any | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    runs_dir: str | Path = "runs",
) -> ControlHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Control API must bind to loopback")
    return ControlHTTPServer((host, port), ControlAPI(service, runs_dir=runs_dir))


def serve(
    service: ControlService | Any | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    runs_dir: str | Path = "runs",
) -> None:
    server = create_server(service, host=host, port=port, runs_dir=runs_dir)
    try:
        server.serve_forever()
    finally:
        server.server_close()
