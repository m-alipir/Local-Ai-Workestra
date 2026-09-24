import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.adapters.llama_server import (
    LlamaServer,
    LlamaServerBusyError,
    LlamaServerEmptyContentError,
    LlamaServerError,
)
from local_agent_orchestrator.services.resource_guard import ResourceSnapshot


def test_base_url():
    server = LlamaServer(
        hf_model="test/model",
        port=9000,
    )

    assert server.base_url == "http://127.0.0.1:9000"


def test_high_reasoning_maps_to_xhigh_effort():
    server = LlamaServer(hf_model="test/model", reasoning="high")

    assert server._reasoning_args()[-1] == "xhigh"


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


def test_chat_keeps_empty_content_without_exposing_reasoning_by_default():
    server = LlamaServer(hf_model="test/model")

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": "",
                    "reasoning_content": "private reasoning",
                },
            }
        ]
    }

    with patch(
        "local_agent_orchestrator.adapters.llama_server.httpx.post",
        return_value=fake_response,
    ):
        assert server.chat("test") == ""


def test_chat_can_require_content_with_diagnostic():
    server = LlamaServer(hf_model="test/model")

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "content": "",
                    "reasoning_content": "private reasoning",
                },
            }
        ]
    }

    with patch(
        "local_agent_orchestrator.adapters.llama_server.httpx.post",
        return_value=fake_response,
    ), pytest.raises(
        LlamaServerEmptyContentError,
        match="empty assistant content.*reasoning_content_present=True",
    ):
        server.chat("test", require_content=True)


def test_chat_forwards_reasoning_controls():
    server = LlamaServer(hf_model="test/model")
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "{}"}}]
    }

    with patch(
        "local_agent_orchestrator.adapters.llama_server.httpx.post",
        return_value=fake_response,
    ) as post:
        server.chat(
            "test",
            reasoning_effort="low",
            chat_template_kwargs={"enable_thinking": False},
        )

    body = post.call_args.kwargs["json"]
    assert body["reasoning_effort"] == "low"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize(
    "message",
    [None, {"content": []}, {"content": {"text": "hello"}}],
)
def test_chat_rejects_non_text_message_content(message):
    server = LlamaServer(hf_model="test/model")

    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": message}]}

    with (
        patch(
            "local_agent_orchestrator.adapters.llama_server.httpx.post",
            return_value=fake_response,
        ),
        pytest.raises(LlamaServerError, match="Unexpected llama-server response"),
    ):
        server.chat("test")


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
    process.pid = 1234
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
        lock_path=tmp_path / "llama.lock",
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


def test_start_uses_local_model_and_flash_attention(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.undo()
    binary = tmp_path / "llama-server"
    model = tmp_path / "model.gguf"
    binary.touch()
    model.touch()
    process = MagicMock()
    process.pid = 1234
    process.poll.return_value = None
    server = LlamaServer(
        hf_model="unused/model",
        binary=binary,
        model_path=model,
        flash_attention=True,
        lock_path=tmp_path / "llama.lock",
    )
    baseline = ResourceSnapshot(
        available_ram_gb=8.0,
        llama_processes=[],
        vram_total_gb=16.0,
        vram_used_gb=2.0,
        vram_free_gb=14.0,
    )
    response = MagicMock(status_code=200)

    with (
        patch(
            "local_agent_orchestrator.adapters.llama_server.assert_safe_to_start_model",
            return_value=baseline,
        ),
        patch(
            "local_agent_orchestrator.adapters.llama_server.subprocess.Popen",
            return_value=process,
        ) as popen,
        patch(
            "local_agent_orchestrator.adapters.llama_server.psutil.Process",
            return_value=MagicMock(create_time=MagicMock(return_value=1.0)),
        ),
        patch(
            "local_agent_orchestrator.adapters.llama_server.httpx.get",
            return_value=response,
        ),
        patch(
            "local_agent_orchestrator.adapters.llama_server.wait_for_model_release"
        ),
    ):
        server.start()
        server.stop()

    command = popen.call_args.args[0]
    assert command[:3] == [str(binary), "-m", str(model)]
    assert command[3:5] == ["-ngl", "99"]
    assert "-fa" in command
    assert command[command.index("-fa") + 1] == "on"


def test_start_waits_for_legitimate_workestra_model_lock(tmp_path, monkeypatch):
    monkeypatch.undo()
    lock_path = tmp_path / "llama.lock"
    owner = LlamaServer(hf_model="test/model", lock_path=lock_path)
    waiting = LlamaServer(hf_model="test/model", lock_path=lock_path, start_timeout=0.01)
    owner._acquire_model_lock()
    try:
        with pytest.raises(LlamaServerBusyError, match="temporarily busy"):
            waiting.start()
    finally:
        owner._release_model_lock()


def test_start_cleans_only_matching_stale_workestra_child(tmp_path, monkeypatch):
    monkeypatch.undo()
    binary = tmp_path / "llama-server"
    binary.touch()
    lock_path = tmp_path / "llama.lock"
    server = LlamaServer(hf_model="test/model", binary=binary, lock_path=lock_path)
    lock_path.write_text(json.dumps({"pid": 1001, "created": 123.0, "executable": str(binary.resolve())}), encoding="utf-8")
    stale = MagicMock()
    stale.create_time.return_value = 123.0
    stale.cmdline.return_value = [str(binary.resolve())]
    spawned = MagicMock(pid=1002)
    spawned.poll.return_value = None
    baseline = ResourceSnapshot(8.0, [], 16.0, 2.0, 14.0)
    with (
        patch("local_agent_orchestrator.adapters.llama_server.psutil.Process", side_effect=[stale, MagicMock(create_time=MagicMock(return_value=124.0))]),
        patch("local_agent_orchestrator.adapters.llama_server.assert_safe_to_start_model", return_value=baseline),
        patch("local_agent_orchestrator.adapters.llama_server.subprocess.Popen", return_value=spawned),
        patch("local_agent_orchestrator.adapters.llama_server.httpx.get", return_value=MagicMock(status_code=200)),
        patch("local_agent_orchestrator.adapters.llama_server.wait_for_model_release"),
    ):
        server.start()
        server.stop()
    stale.terminate.assert_called_once()
    assert lock_path.read_text(encoding="utf-8") == ""


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
