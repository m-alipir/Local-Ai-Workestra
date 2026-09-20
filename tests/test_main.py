from unittest.mock import patch

from local_agent_orchestrator.main import main
from local_agent_orchestrator.services.resource_guard import ResourceGuardError


def test_health_check_returns_nonzero_when_guard_blocks(capsys):
    with (
        patch("local_agent_orchestrator.main.load_settings") as load_settings,
        patch("local_agent_orchestrator.main.get_snapshot") as get_snapshot,
        patch(
            "local_agent_orchestrator.main.assert_safe_to_start_model",
            side_effect=ResourceGuardError("not enough memory"),
        ),
    ):
        load_settings.return_value.resources.minimum_free_ram_gb = 2.0
        load_settings.return_value.resources.minimum_free_vram_gb = 1.0
        get_snapshot.return_value.available_ram_gb = 8.0
        get_snapshot.return_value.vram_total_gb = None
        get_snapshot.return_value.vram_used_gb = None
        get_snapshot.return_value.vram_free_gb = None
        get_snapshot.return_value.llama_processes = []

        assert main() == 1

    assert "Guard: BLOCKED - not enough memory" in capsys.readouterr().out
