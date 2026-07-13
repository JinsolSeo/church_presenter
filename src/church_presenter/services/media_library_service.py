from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from church_presenter.domain.enums import MediaType, SortField
from church_presenter.domain.models import FileItem
from church_presenter.services.file_library_service import scan_library, sort_items


class _WorkerSignals(QObject):
    finished = Signal(str, object, str)


class _LibraryWorker(QRunnable):
    def __init__(
        self,
        token: str,
        folder: Path,
        media_type: MediaType,
        field: SortField,
        descending: bool,
    ) -> None:
        super().__init__()
        self.token = token
        self.folder = folder
        self.media_type = media_type
        self.field = field
        self.descending = descending
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            items = sort_items(
                scan_library(self.folder, self.media_type),
                self.field,
                self.descending,
            )
            self.signals.finished.emit(self.token, items, "")
        except Exception as error:
            self.signals.finished.emit(self.token, [], str(error))


class MediaLibraryCoordinator(QObject):
    """Cancelable background directory scan for video and audio panels."""

    scanned = Signal(object, str)

    def __init__(self) -> None:
        super().__init__()
        self._token = ""
        self._workers: set[_LibraryWorker] = set()

    def scan(
        self,
        folder: Path,
        media_type: MediaType,
        field: SortField,
        descending: bool,
    ) -> None:
        self._token = uuid4().hex
        worker = _LibraryWorker(self._token, folder, media_type, field, descending)
        self._workers.add(worker)
        worker.signals.finished.connect(
            lambda token, items, error, worker=worker: self._finished(worker, token, items, error)
        )
        QThreadPool.globalInstance().start(worker)

    def _finished(
        self,
        worker: _LibraryWorker,
        token: str,
        items: list[FileItem],
        error: str,
    ) -> None:
        self._workers.discard(worker)
        if token != self._token:
            return
        self.scanned.emit(items, error)
