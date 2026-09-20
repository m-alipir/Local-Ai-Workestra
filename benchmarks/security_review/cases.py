from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecurityCase:
    name: str
    task: str
    path: str
    baseline: str
    changed: str
    expected: frozenset[str]


CASES = (
    SecurityCase(
        name="command_injection",
        task="Review the report command change for security issues.",
        path="reporting.py",
        baseline=(
            "from subprocess import run\n\n"
            "def render_report(name: str) -> str:\n"
            "    return run([\"printf\", \"%s\", name], capture_output=True, text=True, check=True).stdout\n"
        ),
        changed=(
            "from subprocess import run\n\n"
            "def render_report(name: str) -> str:\n"
            "    command = f\"printf 'report: %s' {name}\"\n"
            "    return run(command, shell=True, capture_output=True, text=True, check=True).stdout\n"
        ),
        expected=frozenset({"command_injection"}),
    ),
    SecurityCase(
        name="path_traversal",
        task="Review the avatar download change for security issues.",
        path="avatars.py",
        baseline=(
            "from pathlib import Path\n\n"
            "def avatar_path(root: str, name: str) -> Path:\n"
            "    candidate = (Path(root) / name).resolve()\n"
            "    if Path(root).resolve() not in candidate.parents:\n"
            "        raise ValueError(\"invalid avatar\")\n"
            "    return candidate\n"
        ),
        changed=(
            "from pathlib import Path\n\n"
            "def avatar_path(root: str, name: str) -> Path:\n"
            "    return Path(root) / name\n"
        ),
        expected=frozenset({"path_traversal"}),
    ),
    SecurityCase(
        name="secret_exposure",
        task="Review the API client logging change for security issues.",
        path="client_logging.py",
        baseline=(
            "import logging\n\n"
            "logger = logging.getLogger(__name__)\n\n"
            "def log_request(user_id: str) -> None:\n"
            "    logger.info(\"request user=%s\", user_id)\n"
        ),
        changed=(
            "import logging\n\n"
            "logger = logging.getLogger(__name__)\n\n"
            "def log_request(user_id: str, api_token: str) -> None:\n"
            "    logger.info(\"request user=%s token=%s\", user_id, api_token)\n"
        ),
        expected=frozenset({"secret_exposure"}),
    ),
    SecurityCase(
        name="clean_control",
        task="Review the display-name normalization change for security issues.",
        path="names.py",
        baseline=(
            "def display_name(value: str) -> str:\n"
            "    return value\n"
        ),
        changed=(
            "def display_name(value: str) -> str:\n"
            "    return \" \".join(value.split())\n"
        ),
        expected=frozenset(),
    ),
    SecurityCase(
        name="combined_input_boundary",
        task="Review the file export endpoint change for security issues.",
        path="exports.py",
        baseline=(
            "from pathlib import Path\n\n"
            "def export_file(root: str, name: str) -> bytes:\n"
            "    path = (Path(root) / name).resolve()\n"
            "    if Path(root).resolve() not in path.parents:\n"
            "        raise ValueError(\"invalid file\")\n"
            "    return path.read_bytes()\n"
        ),
        changed=(
            "import subprocess\n\n"
            "def export_file(root: str, name: str) -> bytes:\n"
            "    command = f\"cat {root}/{name}\"\n"
            "    return subprocess.check_output(command, shell=True)\n"
        ),
        expected=frozenset({"command_injection", "path_traversal"}),
    ),
)


CASE_BY_NAME = {case.name: case for case in CASES}
