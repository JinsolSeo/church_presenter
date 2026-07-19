from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QAbstractItemView, QBoxLayout, QListView

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
    assert panel.venue_target_check.parentWidget() is panel.file_list.parentWidget()
    assert panel.broadcast_target_check.parentWidget() is panel.file_list.parentWidget()
    assert panel.venue_target_check.text() == "현장 Preview"
    assert panel.broadcast_target_check.text() == "송출 Preview"
    assert panel.folder_label.parentWidget() is panel.file_list.parentWidget()
    assert panel.thumbnail_list.gridSize().width() == 166
    assert panel.thumbnail_list.gridSize().height() == 122
    assert panel.page_controls_layout.indexOf(panel.page_spin) == 0
    assert panel.page_controls_layout.indexOf(panel.go_button) == 1
    assert panel.action_layout.direction() is QBoxLayout.Direction.LeftToRight
    page_center = panel.page_spin.mapTo(panel, QPoint()).y() + panel.page_spin.height() // 2
    take_center = panel.take_button.mapTo(panel, QPoint()).y() + panel.take_button.height() // 2
    assert abs(page_center - take_center) <= 1
    assert not hasattr(panel, "preview_label")
    assert not hasattr(panel, "live_label")
    qtbot.waitUntil(lambda: panel.file_list.count() == 1, timeout=5000)
    preview_spy = QSignalSpy(panel.preview_requested)
    ready_spy = QSignalSpy(panel.preview_ready)
    panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: panel.thumbnail_list.count() == 2, timeout=5000)
    panel.thumbnail_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: ready_spy.count() >= 1, timeout=10000)
    assert preview_spy.count() >= 1
    assert panel.target_role is ChannelRole.VENUE
    assert preview_spy.at(preview_spy.count() - 1)[0] == ChannelRole.VENUE.value
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
    panel.broadcast_target_check.setChecked(True)
    assert panel.venue_target_check.isChecked()
    assert panel.broadcast_target_check.isChecked()
    assert panel.target_roles == (ChannelRole.VENUE, ChannelRole.BROADCAST)
    assert panel.link_outputs
    assert not panel.take_button.isEnabled()
    panel.navigate(1)
    qtbot.waitUntil(lambda: linked_spy.count() >= 2, timeout=10000)
    assert panel.preview_page == 1
    assert panel.thumbnail_list.dragDropMode() is QAbstractItemView.DragDropMode.NoDragDrop
    assert panel.thumbnail_list.movement() is QListView.Movement.Static
    assert panel.thumbnail_list.flow() is QListView.Flow.LeftToRight
    assert panel.page_order == [0, 1]
    assert [
        panel.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(panel.thumbnail_list.count())
    ] == [0, 1]
    panel.move_preview(-1)
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
    assert panel.page_order == [0, 1]
    assert panel.thumbnail_list.currentRow() == 1
    assert panel.thumbnail_list.item(0).data(Qt.ItemDataRole.UserRole) == 0
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


def test_pdf_library_uses_fixed_filename_descending_order(qtbot, tmp_path: Path) -> None:
    create_pdf(tmp_path / "alpha.pdf")
    create_pdf(tmp_path / "zulu.pdf")
    panel = PdfPanel(
        PdfRenderCoordinator(),
        tmp_path,
        sort_field=SortField.MODIFIED,
        descending=False,
    )
    qtbot.addWidget(panel)
    panel.show()

    qtbot.waitUntil(lambda: panel.file_list.count() == 2, timeout=5000)

    assert panel.sort_field is SortField.NAME
    assert panel.descending is True
    assert panel.target_role is ChannelRole.VENUE
    assert panel.venue_target_check.isChecked()
    assert not panel.broadcast_target_check.isChecked()
    assert not hasattr(panel, "target_combo")
    assert not hasattr(panel, "link_outputs_check")
    assert not hasattr(panel, "sort_combo")
    assert not hasattr(panel, "order_button")
    assert panel.file_list.item(0).text().startswith("zulu.pdf")
    assert panel.file_list.item(1).text().startswith("alpha.pdf")
