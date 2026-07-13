from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from church_presenter.services.pdf_service import (
    PdfImageCache,
    contain_size,
    make_cache_key,
)


def test_contain_landscape_and_portrait() -> None:
    assert contain_size(1920, 1080, 1280, 720) == (0, 0, 1280, 720)
    assert contain_size(600, 800, 1280, 720) == (370, 0, 540, 720)
    assert contain_size(800, 600, 1920, 1080) == (240, 0, 1440, 1080)


def test_cache_key_changes_with_size_and_modification(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"first")
    first = make_cache_key(path, 0, QSize(320, 180))
    size_changed = make_cache_key(path, 0, QSize(640, 360))
    path.write_bytes(b"updated content")
    modified = make_cache_key(path, 0, QSize(320, 180))
    assert first != size_changed
    assert first != modified


def test_bounded_cache_and_path_invalidation(tmp_path: Path) -> None:
    first_path = tmp_path / "first.pdf"
    second_path = tmp_path / "second.pdf"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first_key = make_cache_key(first_path, 0, (100, 100))
    second_key = make_cache_key(second_path, 0, (100, 100))
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    cache = PdfImageCache(max_items=1)
    cache.put(first_key, image)
    cache.put(second_key, image)
    assert len(cache) == 1
    assert cache.get(first_key) is None
    assert cache.get(second_key) is not None
    cache.invalidate_path(second_path)
    assert len(cache) == 0
