from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.adapters.llama_server import LlamaServer
from local_agent_orchestrator.services.resource_guard import ResourceSnapshot


def test_base_url():
    server = LlamaServer(
        hf_model="test/model",
        port=9000,
    )

    assert server.base_url == "http://127.0.0.1:9000"


def test_chat_returns_content():
    server = LlamaServer(hf_model="test/model")

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "hello"
                }
            }
        ]
    }

    with patch(
        "local_agent_orchestrator.adapters.llama_server.httpx.post",
        return_value=fake_response,
    ):
        result = server.chat("test")

    assert result == "hello"


def test_chat_forwards_optional_response_format():
    server = LlamaServer(hf_model="test/model")
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "{}"}}]
    }
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": {"type": "object"}},
    }

    with patch(
        "local_agent_orchestrator.adapters.llama_server.httpx.post",
        return_value=fake_response,
    ) as post:
        server.chat("test", response_format=response_format)

    assert post.call_args.kwargs["json"]["response_format"] == response_format


def test_stop_terminates_process():
    server = LlamaServer(hf_model="test/model")

    process = MagicMock()
    process.poll.return_value = None
    server.process = process

    server.stop()

    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert server.process is None


def test_stop_releases_baseline_without_process():
    server = LlamaServer(hf_model="test/model")
    baseline = ResourceSnapshot(
        available_ram_gb=8.0,
        llama_processes=[],
        vram_total_gb=16.0,
        vram_used_gb=2.0,
        vram_free_gb=14.0,
    )
    server._baseline_resources = baseline

    with patch(
        "local_agent_orchestrator.adapters.llama_server.wait_for_model_release"
    ) as wait:
        server.stop()

    wait.assert_called_once_with(
        baseline=baseline,
        timeout=20,
    )
    assert server._baseline_resources is None


def test_start_cleans_baseline_when_spawn_fails(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.undo()
    binary = tmp_path / "llama-server"
    binary.touch()
    server = LlamaServer(
        hf_model="test/model",
        binary=binary,
    )
    baseline = ResourceSnapshot(
        available_ram_gb=8.0,
        llama_processes=[],
        vram_total_gb=16.0,
        vram_used_gb=2.0,
        vram_free_gb=14.0,
    )

    with (
        patch(
            "local_agent_orchestrator.adapters.llama_server.assert_safe_to_start_model",
            return_value=baseline,
        ),
        patch(
            "local_agent_orchestrator.adapters.llama_server.subprocess.Popen",
            side_effect=OSError("spawn failed"),
        ),
        patch(
            "local_agent_orchestrator.adapters.llama_server.wait_for_model_release"
        ) as wait,
        pytest.raises(OSError, match="spawn failed"),
    ):
        server.start()

    wait.assert_called_once_with(
        baseline=baseline,
        timeout=20,
    )
    assert server.process is None
    assert server._baseline_resources is None


def test_context_manager_stops_after_body_failure():
    server = LlamaServer(hf_model="test/model")

    with (
        patch.object(server, "start") as start,
        patch.object(server, "stop") as stop,
        pytest.raises(RuntimeError, match="body failure"),
    ):
        with server:
            raise RuntimeError("body failure")

    start.assert_called_once()
    stop.assert_called_once()
