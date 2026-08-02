from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

UPDATE_REQUIREMENTS = ("yt-dlp[default]", "python-mpv<2")
MAX_OUTPUT_CHARACTERS = 32_000


@dataclass(frozen=True, slots=True)
class FeatureUpdateResult:
    success: bool
    message: str
    details: str
    restart_required: bool = False


def project_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("프로젝트 루트를 찾을 수 없어 기능을 최신화할 수 없습니다.")


def current_venv_python(root: Path | None = None) -> Path:
    """Return the running project's .venv interpreter without falling back globally."""
    prefix = Path(sys.prefix)
    expected_prefix = (root or project_root()) / ".venv"
    if sys.prefix == sys.base_prefix or prefix.resolve() != expected_prefix.resolve():
        raise RuntimeError(
            "프로젝트 .venv의 Python으로 실행된 경우에만 기능을 최신화할 수 있습니다."
        )
    executable = Path(sys.executable)
    if not executable.is_file():
        raise RuntimeError(f".venv Python을 찾을 수 없습니다: {executable}")
    try:
        executable.absolute().relative_to(prefix.absolute())
    except ValueError as error:
        raise RuntimeError(
            f"실행 중인 Python이 프로젝트 .venv에 속하지 않습니다: {executable}"
        ) from error
    return executable


def feature_update_command() -> tuple[str, tuple[str, ...]]:
    """Build one cross-platform pip command tied to the running .venv."""
    return (
        str(current_venv_python()),
        (
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--upgrade",
            *UPDATE_REQUIREMENTS,
        ),
    )


def installed_feature_versions() -> str:
    entries: list[str] = []
    for distribution, label in (
        ("yt-dlp", "yt-dlp"),
        ("yt-dlp-ejs", "yt-dlp-ejs"),
        ("python-mpv", "python-mpv"),
    ):
        try:
            installed = version(distribution)
        except PackageNotFoundError:
            installed = "설치되지 않음"
        entries.append(f"{label} {installed}")
    return "\n".join(entries)


class FeatureUpdateService(QObject):
    """Update YouTube Python components in a child process and keep the UI responsive."""

    started = Signal()
    finished = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._collect_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self._output = ""
        self._result_reported = False

    @property
    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(self) -> None:
        if self.is_running:
            return
        program, arguments = feature_update_command()
        self._output = ""
        self._result_reported = False
        self.process.setProgram(program)
        self.process.setArguments(list(arguments))
        self.process.start()
        self.started.emit()

    def _collect_output(self) -> None:
        raw_output = self.process.readAllStandardOutput().data()
        chunk = bytes(raw_output).decode("utf-8", errors="replace")
        self._output = (self._output + chunk)[-MAX_OUTPUT_CHARACTERS:]

    def _process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        self._collect_output()
        if self._result_reported:
            return
        self._result_reported = True
        success = exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0
        if not success:
            self.finished.emit(
                FeatureUpdateResult(
                    False,
                    "기능 최신화에 실패했습니다. 네트워크와 상세 내용을 확인하십시오.",
                    self._output.strip(),
                )
            )
            return

        runtime_notice = (
            "Deno가 감지되었습니다."
            if shutil.which("deno")
            else "Deno가 PATH에서 감지되지 않았습니다. YouTube 재생에 Deno 2.3 이상이 필요합니다."
        )
        self.finished.emit(
            FeatureUpdateResult(
                True,
                "기능 최신화가 완료되었습니다. 앱을 다시 시작하십시오.\n" + runtime_notice,
                f"{installed_feature_versions()}\n\n{self._output.strip()}",
                restart_required=True,
            )
        )

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart or self._result_reported:
            return
        self._result_reported = True
        self.finished.emit(
            FeatureUpdateResult(
                False,
                ".venv Python 업데이트 프로세스를 시작하지 못했습니다.",
                self.process.errorString(),
            )
        )
