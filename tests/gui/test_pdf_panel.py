from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QAbstractItemView

from church_presenter.domain.enums import Availability, ChannelRole, SortField
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.ui.panels.pdf_panel import PdfPanel


def create_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=800, height=600)
    page.insert_text((72, 72), "Church Presenter PDF smoke test", fontsize=24)
    document.new_page(width=600, height=800)
    document.save(path)
    document.close()


def test_pdf_scan_thumbnail_and_preview_ready(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "service.pdf"
    create_pdf(path)
    panel = PdfPanel(PdfRenderCoordinator(), tmp_path)
    qtbot.addWidget(panel)
    panel.show()
    panel.resize(1200, 700)
    qtbot.wait(20)
    assert panel.file_list.minimumWidth() >= 300
    assert panel.splitter.sizes()[0] >= 300
    qtbot.waitUntil(lambda: panel.file_list.count() == 1, timeout=5000)
    preview_spy = QSignalSpy(panel.preview_requested)
    ready_spy = QSignalSpy(panel.preview_ready)
    panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: panel.thumbnail_list.count() == 2, timeout=5000)
    panel.thumbnail_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: ready_spy.count() >= 1, timeout=10000)
    assert preview_spy.count() >= 1
    assert preview_spy.at(preview_spy.count() - 1)[0] == ChannelRole.BROADCAST.value
    assert ready_spy.at(ready_spy.count() - 1)[1] is True
    assert panel.status.text().startswith("준비 완료")

    both_spy = QSignalSpy(panel.send_to_both_requested)
    both_ready_spy = QSignalSpy(panel.preview_ready)
    panel.send_to_both()
    qtbot.waitUntil(lambda: both_ready_spy.count() >= 2, timeout=10000)
    assert both_spy.at(0)[1] is False
    roles = {both_ready_spy.at(index)[0] for index in range(both_ready_spy.count())}
    assert roles == {ChannelRole.BROADCAST.value, ChannelRole.VENUE.value}
    assert panel.status.text().startswith("두 Preview 준비 완료")

    linked_spy = QSignalSpy(panel.send_to_both_requested)
    panel.link_outputs_check.setChecked(True)
    assert not panel.target_combo.isEnabled()
    assert not panel.take_button.isEnabled()
    panel.navigate(1)
    qtbot.waitUntil(lambda: linked_spy.count() >= 2, timeout=10000)
    assert panel.preview_page == 1
    assert panel.thumbnail_list.dragDropMode() is QAbstractItemView.DragDropMode.InternalMove
    moved = panel.thumbnail_list.model().moveRows(
        QModelIndex(),
        0,
        1,
        QModelIndex(),
        2,
    )
    assert moved is True
    assert panel.page_order == [1, 0]
    assert panel.page_orders[str(path.resolve())] == [1, 0]
    panel.move_preview(1)
    assert panel.preview_page == 0


def test_pdf_last_selection_is_restored(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "remembered.pdf"
    create_pdf(path)
    panel = PdfPanel(
        PdfRenderCoordinator(),
        tmp_path,
        restore_path=path,
        restore_page=1,
        page_orders={str(path.resolve()): [1, 0]},
    )
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitUntil(lambda: panel.current_path == path, timeout=5000)
    assert panel.preview_page == 1
    assert panel.page_order == [1, 0]
    assert panel.thumbnail_list.item(0).data(Qt.ItemDataRole.UserRole) == 1
    assert panel.page_spin.value() == 2


def test_corrupt_pdf_is_visible_as_error(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    panel = PdfPanel(PdfRenderCoordinator(), tmp_path)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitUntil(lambda: len(panel.items) == 1, timeout=5000)
    assert panel.items[0].availability is Availability.ERROR
    assert panel.file_list.item(0).text().startswith("⚠")
    panel.sort_combo.setCurrentIndex(panel.sort_combo.findData(SortField.MODIFIED))
    assert panel.sort_field is SortField.MODIFIED
