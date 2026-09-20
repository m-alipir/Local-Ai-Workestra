from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(slots=True)
class ResourceSnapshot:
    available_ram_gb: float
    llama_processes: list[tuple[int, str]]
    vram_total_gb: float | None
    vram_used_gb: float | None
    vram_free_gb: float | None


class ResourceGuardError(RuntimeError):
    pass


def _is_llama_process(name: str, cmdline: list[str]) -> bool:
    text = " ".join([name, *cmdline]).lower()

    return any(
        marker in text
        for marker in (
            "llama-server",
            "llama-cli",
            "llama download",
            "llama serve",
            "llama cli",
        )
    )


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _get_amd_vram() -> tuple[float | None, float | None, float | None]:
    drm_root = Path("/sys/class/drm")

    for card in sorted(drm_root.glob("card[0-9]*")):
        device = card / "device"

        total = _read_int(device / "mem_info_vram_total")
        used = _read_int(device / "mem_info_vram_used")

        if total is None or used is None:
            continue

        total_gb = total / (1024 ** 3)
        used_gb = used / (1024 ** 3)
        free_gb = max(total_gb - used_gb, 0.0)

        return total_gb, used_gb, free_gb

    return None, None, None


def get_snapshot() -> ResourceSnapshot:
    memory = psutil.virtual_memory()
    available_ram_gb = memory.available / (1024 ** 3)

    llama_processes: list[tuple[int, str]] = []

    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = process.info.get("name") or ""
            cmdline = process.info.get("cmdline") or []

            if _is_llama_process(name, cmdline):
                command = " ".join(cmdline) or name
                llama_processes.append((process.pid, command))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    vram_total_gb, vram_used_gb, vram_free_gb = _get_amd_vram()

    return ResourceSnapshot(
        available_ram_gb=available_ram_gb,
        llama_processes=llama_processes,
        vram_total_gb=vram_total_gb,
        vram_used_gb=vram_used_gb,
        vram_free_gb=vram_free_gb,
    )


def assert_safe_to_start_model(
    minimum_free_ram_gb: float,
    minimum_free_vram_gb: float,
) -> ResourceSnapshot:
    snapshot = get_snapshot()

    if snapshot.llama_processes:
        processes = ", ".join(
            f"{pid}: {command}" for pid, command in snapshot.llama_processes
        )
        raise ResourceGuardError(
            f"Another llama process is already running: {processes}"
        )

    if snapshot.available_ram_gb < minimum_free_ram_gb:
        raise ResourceGuardError(
            "Not enough free RAM to start a model: "
            f"{snapshot.available_ram_gb:.2f} GB available, "
            f"{minimum_free_ram_gb:.2f} GB required."
        )

    if (
        snapshot.vram_free_gb is not None
        and snapshot.vram_free_gb < minimum_free_vram_gb
    ):
        raise ResourceGuardError(
            "Not enough free VRAM to start a model: "
            f"{snapshot.vram_free_gb:.2f} GB available, "
            f"{minimum_free_vram_gb:.2f} GB required."
        )

    return snapshot


def wait_for_model_release(
    baseline: ResourceSnapshot,
    timeout: float,
    poll_interval: float = 0.5,
    ram_tolerance_gb: float = 1.0,
    vram_tolerance_gb: float = 0.5,
) -> ResourceSnapshot:
    import time

    deadline = time.monotonic() + timeout
    last_snapshot = get_snapshot()

    while time.monotonic() < deadline:
        snapshot = get_snapshot()
        last_snapshot = snapshot

        processes_released = not snapshot.llama_processes

        ram_released = (
            snapshot.available_ram_gb
            >= baseline.available_ram_gb - ram_tolerance_gb
        )

        if (
            baseline.vram_used_gb is None
            or snapshot.vram_used_gb is None
        ):
            vram_released = True
        else:
            vram_released = (
                snapshot.vram_used_gb
                <= baseline.vram_used_gb + vram_tolerance_gb
            )

        if (
            processes_released
            and ram_released
            and vram_released
        ):
            return snapshot

        time.sleep(poll_interval)

    raise ResourceGuardError(
        "Model resources were not released before timeout. "
        f"llama_processes={last_snapshot.llama_processes}, "
        f"available_ram_gb={last_snapshot.available_ram_gb:.2f}, "
        f"vram_used_gb={last_snapshot.vram_used_gb}"
    )
