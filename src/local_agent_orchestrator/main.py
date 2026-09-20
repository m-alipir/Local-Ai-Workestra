from local_agent_orchestrator.core.config import load_settings
from local_agent_orchestrator.services.resource_guard import (
    ResourceGuardError,
    assert_safe_to_start_model,
    get_snapshot,
)


def main() -> int:
    try:
        settings = load_settings()
    except Exception as exc:
        print(f"local-agent-orchestrator: error: {exc}")
        return 1

    snapshot = get_snapshot()

    print(f"Available RAM: {snapshot.available_ram_gb:.2f} GB")

    if snapshot.vram_total_gb is None:
        print("VRAM: unavailable")
    else:
        print(
            f"VRAM: {snapshot.vram_used_gb:.2f} GB used / "
            f"{snapshot.vram_total_gb:.2f} GB total / "
            f"{snapshot.vram_free_gb:.2f} GB free"
        )

    if snapshot.llama_processes:
        print("Llama processes:")
        for pid, command in snapshot.llama_processes:
            print(f"  {pid}: {command}")
    else:
        print("Llama processes: none")

    try:
        assert_safe_to_start_model(
            settings.resources.minimum_free_ram_gb,
            settings.resources.minimum_free_vram_gb,
        )
    except ResourceGuardError as exc:
        print(f"Guard: BLOCKED - {exc}")
        return 1
    else:
        print("Guard: SAFE")

    return 0


if __name__ == "__main__":
    main()
