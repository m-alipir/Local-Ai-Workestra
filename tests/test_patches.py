import pytest

from local_agent_orchestrator.services.patches import (
    PatchError,
    apply_patch_set,
    parse_patch_response,
)
from local_agent_orchestrator.services.workspace import Workspace


def test_parse_patch_response():
    result = parse_patch_response(
        '{"files":[{"path":"src/app.py","content":"print(123)\\n"}]}'
    )

    assert result.files[0].path == "src/app.py"
    assert result.files[0].content == "print(123)\n"


def test_parse_fenced_json():
    result = parse_patch_response(
        '```json\n'
        '{"files":[{"path":"a.py","content":"x = 1\\n"}]}\n'
        '```'
    )

    assert result.files[0].path == "a.py"


def test_invalid_json():
    with pytest.raises(PatchError):
        parse_patch_response("not json")


def test_apply_patch_set(tmp_path):
    workspace = Workspace(tmp_path)

    patch_set = parse_patch_response(
        '{"files":[{"path":"src/app.py","content":"print(123)\\n"}]}'
    )

    changed = apply_patch_set(
        workspace,
        patch_set,
    )

    assert changed == ["src/app.py"]
    assert workspace.read_text("src/app.py") == "print(123)\n"


def test_apply_blocks_workspace_escape(tmp_path):
    workspace = Workspace(tmp_path)

    patch_set = parse_patch_response(
        '{"files":[{"path":"../evil.txt","content":"bad"}]}'
    )

    with pytest.raises(Exception):
        apply_patch_set(
            workspace,
            patch_set,
        )


def test_parse_json_with_trailing_text():
    import json

    payload = json.dumps({
        "files": [
            {
                "path": "x.py",
                "content": "x = 1\n",
            }
        ]
    })

    result = parse_patch_response(payload + "\nDone.")

    assert result.files[0].path == "x.py"
    assert result.files[0].content == "x = 1\n"
