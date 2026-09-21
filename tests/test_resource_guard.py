from unittest.mock import patch

import pytest

from local_agent_orchestrator.services.resource_guard import (
    ResourceGuardError,
    ResourceSnapshot,
    _is_llama_process,
    assert_safe_to_start_model,
)


def make_snapshot(
    ram: float = 8.0,
    processes: list[tuple[int, str]] | None = None,
    vram_free: float = 8.0,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        available_ram_gb=ram,
        llama_processes=processes or [],
        vram_total_gb=16.0,
        vram_used_gb=16.0 - vram_free,
        vram_free_gb=vram_free,
    )


def test_guard_allows_safe_system():
    snapshot = make_snapshot()

    with patch(
        "local_agent_orchestrator.services.resource_guard.get_snapshot",
        return_value=snapshot,
    ):
        result = assert_safe_to_start_model(2.0, 1.0)

    assert result.available_ram_gb == 8.0


def test_guard_blocks_existing_llama_process():
    snapshot = make_snapshot(processes=[(1234, "llama-server")])

    with patch(
        "local_agent_orchestrator.services.resource_guard.get_snapshot",
        return_value=snapshot,
    ):
        with pytest.raises(ResourceGuardError):
            assert_safe_to_start_model(2.0, 1.0)


def test_process_detection_uses_executable_not_shell_text():
    assert _is_llama_process("llama-server", [])
    assert _is_llama_process("python", ["/opt/llama", "serve"])
    assert not _is_llama_process(
        "bash",
        ["bash", "-c", "pgrep -af llama-server"],
    )
    assert not _is_llama_process(
        "python",
        ["python", "-c", "print('llama-server')"],
    )


def test_guard_blocks_low_ram():
    snapshot = make_snapshot(ram=1.0)

    with patch(
        "local_agent_orchestrator.services.resource_guard.get_snapshot",
        return_value=snapshot,
    ):
        with pytest.raises(ResourceGuardError):
            assert_safe_to_start_model(2.0, 1.0)


def test_guard_blocks_low_vram():
    snapshot = make_snapshot(vram_free=0.5)

    with patch(
        "local_agent_orchestrator.services.resource_guard.get_snapshot",
        return_value=snapshot,
    ):
        with pytest.raises(ResourceGuardError):
            assert_safe_to_start_model(2.0, 1.0)
