from __future__ import annotations

import pytest

from app.agent_framework.tools import create_default_registry


def test_local_file_tools_stay_inside_configured_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_FILE_ACCESS_ROOT", str(tmp_path))
    registry = create_default_registry()

    result = registry.invoke(
        "write_local_file",
        {"path": "notes/today.txt", "content": "hello"},
        context={"approval_granted": True},
    )
    assert "today.txt" in result

    content = registry.invoke("read_local_file", {"path": "notes/today.txt"})
    assert content == "hello"

    with pytest.raises(PermissionError):
        registry.invoke("read_local_file", {"path": "../outside.txt"})

    with pytest.raises(PermissionError):
        registry.invoke(
            "write_local_file",
            {"path": str(tmp_path.parent / "outside.txt"), "content": "nope"},
            context={"approval_granted": True},
        )
