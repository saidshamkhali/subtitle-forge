from pathlib import Path

from subtitle_forge.executables import resolve_executable


def test_resolve_executable_returns_none_for_missing_command():
    assert resolve_executable("definitely-not-subtitle-forge-command") is None


def test_resolve_executable_returns_python():
    resolved = resolve_executable("python")

    assert resolved is not None
    assert Path(resolved).exists()
