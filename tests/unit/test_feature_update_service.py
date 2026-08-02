from __future__ import annotations

import sys
from pathlib import Path

import pytest

from church_presenter.services.feature_update_service import (
    UPDATE_REQUIREMENTS,
    current_venv_python,
    feature_update_command,
)


def test_feature_update_command_uses_running_dot_venv_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv = tmp_path / ".venv"
    executable = venv / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "base-python"))
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(
        "church_presenter.services.feature_update_service.project_root",
        lambda: tmp_path,
    )

    program, arguments = feature_update_command()

    assert program == str(executable)
    assert arguments[:6] == (
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--upgrade",
    )
    assert arguments[6:] == UPDATE_REQUIREMENTS


def test_feature_update_refuses_non_venv_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "python"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "python"))

    with pytest.raises(RuntimeError, match=r"\.venv"):
        current_venv_python(tmp_path)


def test_feature_update_refuses_differently_named_virtual_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "python"))

    with pytest.raises(RuntimeError, match=r"\.venv"):
        current_venv_python(tmp_path)


def test_feature_update_refuses_another_projects_dot_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    other_venv = tmp_path / "other" / ".venv"
    monkeypatch.setattr(sys, "prefix", str(other_venv))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "python"))

    with pytest.raises(RuntimeError, match=r"프로젝트 \.venv"):
        current_venv_python(tmp_path / "project")
