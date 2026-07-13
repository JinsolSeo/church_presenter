from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import fitz
from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, Signal
from PySide6.QtGui import QImage


@dataclass(frozen=True, slots=True)
class PdfCacheKey:
    path: str
    modified_time_ns: int
    page: int
    width: int
    height: int


def make_cache_key(path: Path, page: int, size: QSize | tuple[int, int]) -> PdfCacheKey:
    """Create a key that invalidates when the source file changes."""
    width, height = (size.width(), size.height()) if isinstance(size, QSize) else size
    stat = path.stat()
    return PdfCacheKey(str(path.resolve()), stat.st_mtime_ns, page, width, height)


def contain_size(
    source_width: float,
    source_height: float,
    target_width: int,
    target_height: int,
) -> tuple[int, int, int, int]:
    """Return centered x, y, width, height without cropping."""
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("source and target dimensions must be positive")
    scale = min(target_width / source_width, target_height / source_height)
    width = max(1, round(source_width * scale))
    height = max(1, round(source_height * scale))
    return (target_width - width) // 2, (target_height - height) // 2, width, height


class PdfImageCache:
    """Thread-safe bounded LRU cache."""

    def __init__(self, max_items: int = 96) -> None:
        self.max_items = max_items
        self._items: OrderedDict[PdfCacheKey, QImage] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: PdfCacheKey) -> QImage | None:
        with self._lock:
            image = self._items.get(key)
            if image is not None:
                self._items.move_to_end(key)
                return image.copy()
        return None

    def put(self, key: PdfCacheKey, image: QImage) -> None:
        with self._lock:
            self._items[key] = image.copy()
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def invalidate_path(self, path: Path) -> None:
        resolved = str(path.resolve())
        with self._lock:
            for key in [key for key in self._items if key.path == resolved]:
                del self._items[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def pdf_page_count(path: Path) -> int:
    """Probe a PDF and close it immediately."""
    with fitz.open(path) as document:
        return int(document.page_count)


def render_pdf_page(path: Path, page: int, size: QSize) -> QImage:
    """Render one page to a transparent QImage at contain resolution."""
    if size.width() < 1 or size.height() < 1:
        raise ValueError("render size must be positive")
    with fitz.open(path) as document:
        if not 0 <= page < document.page_count:
            raise IndexError("PDF page is out of range")
        pdf_page = document.load_page(page)
        rect = pdf_page.rect
        _, _, width, height = contain_size(rect.width, rect.height, size.width(), size.height())
        matrix = fitz.Matrix(width / rect.width, height / rect.height)
        pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
        image = QImage(
            pixmap.samples,
            pixmap.width,
            pixmap.height,
            pixmap.stride,
            QImage.Format.Format_RGB888,
        )
        return image.copy()


class _WorkerSignals(QObject):
    completed = Signal(object, object, str, object)


class _RenderTask(QRunnable):
    def __init__(
        self,
        key: PdfCacheKey,
        path: Path,
        page: int,
        size: QSize,
        token: object,
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.key = key
        self.path = path
        self.page = page
        self.size = size
        self.token = token
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            image = render_pdf_page(self.path, self.page, self.size)
            error = ""
        except Exception as caught:  # worker boundary; surfaced to the UI
            image = QImage()
            error = str(caught)
        self.signals.completed.emit(self.key, image, error, self.token)


class PdfRenderCoordinator(QObject):
    """Asynchronous cached rendering coordinator."""

    rendered = Signal(object, object, str, object)

    def __init__(self, cache: PdfImageCache | None = None) -> None:
        super().__init__()
        self.cache = cache or PdfImageCache()
        self.pool = QThreadPool.globalInstance()
        self._tasks: set[_RenderTask] = set()
        self._cancelled_tokens: set[object] = set()

    def request(
        self,
        path: Path,
        page: int,
        size: QSize,
        token: object,
        *,
        priority: int = 0,
    ) -> None:
        try:
            key = make_cache_key(path, page, size)
        except OSError as error:
            self.rendered.emit(None, QImage(), str(error), token)
            return
        cached = self.cache.get(key)
        if cached is not None:
            self.rendered.emit(key, cached, "", token)
            return
        task = _RenderTask(key, path, page, QSize(size), token)
        self._tasks.add(task)
        task.signals.completed.connect(self._finished)
        self.pool.start(task, priority)

    def cancel(self, token: object) -> None:
        """Cancel queued work and suppress results from already-running work."""
        if not token:
            return
        matching = [task for task in self._tasks if task.token == token]
        if not matching:
            return
        self._cancelled_tokens.add(token)
        for task in matching:
            try:
                was_queued = self.pool.tryTake(task)
            except RuntimeError:
                self._tasks.discard(task)
                continue
            if was_queued:
                self._tasks.discard(task)
        if not any(task.token == token for task in self._tasks):
            self._cancelled_tokens.discard(token)

    def _finished(self, key: PdfCacheKey, image: QImage, error: str, token: object) -> None:
        sender = self.sender()
        for task in tuple(self._tasks):
            if task.signals is sender:
                self._tasks.discard(task)
                break
        if not error and not image.isNull():
            self.cache.put(key, image)
        if token in self._cancelled_tokens:
            self._cancelled_tokens.discard(token)
            return
        self.rendered.emit(key, image, error, token)
