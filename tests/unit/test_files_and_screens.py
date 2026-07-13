from __future__ import annotations

import os
from pathlib import Path

from church_presenter.domain.enums import MediaType, SortField
from church_presenter.domain.models import ScreenInfo
from church_presenter.services.file_library_service import scan_library, sort_items
from church_presenter.services.screen_service import MockScreenService, validate_role_assignment


def test_file_name_and_modified_sort(tmp_path: Path) -> None:
    zulu = tmp_path / "Zulu.pdf"
    alpha = tmp_path / "alpha.pdf"
    zulu.write_bytes(b"z")
    alpha.write_bytes(b"a")
    os.utime(zulu, (100, 100))
    os.utime(alpha, (200, 200))
    items = scan_library(tmp_path, MediaType.PDF)
    assert [item.display_name for item in sort_items(items, SortField.NAME)] == [
        "alpha.pdf",
        "Zulu.pdf",
    ]
    assert [item.display_name for item in sort_items(items, SortField.MODIFIED)] == [
        "Zulu.pdf",
        "alpha.pdf",
    ]
    assert sort_items(items, SortField.MODIFIED, True)[0].display_name == "alpha.pdf"


def test_mock_screens_and_assignment_policy(qapp) -> None:
    screens = [
        ScreenInfo("virtual-1", "Virtual", 0, 0, 1280, 720, 2.0, True),
        ScreenInfo("virtual-2", "Virtual 2", 1280, 0, 1920, 1080),
    ]
    service = MockScreenService(screens)
    assert service.screens() == screens
    assert validate_role_assignment("virtual-1", "virtual-2", simulation_mode=False)[0]
    assert not validate_role_assignment("virtual-1", "virtual-1", simulation_mode=False)[0]
    assert validate_role_assignment("virtual-1", "virtual-1", simulation_mode=True)[0]
