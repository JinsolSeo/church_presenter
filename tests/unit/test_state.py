from __future__ import annotations

from pathlib import Path

from church_presenter.domain.enums import ChannelRole, ContentType
from church_presenter.domain.models import (
    Content,
    SubtitleStyle,
    default_bible_reference_style,
)
from church_presenter.domain.state import ApplicationState


def test_preview_does_not_change_live_and_take_does() -> None:
    state = ApplicationState()
    content = Content.subtitle("Hello", 0, SubtitleStyle(), "#00FF00")
    state.set_preview(ChannelRole.BROADCAST, content)
    assert state.broadcast.live_content.kind is ContentType.BLACK
    assert state.take(ChannelRole.BROADCAST) == (True, "")
    assert state.broadcast.live_content == content
    assert state.venue.live_content.kind is ContentType.BLACK


def test_venue_rejects_subtitles_and_preserves_live() -> None:
    state = ApplicationState()
    state.set_preview(
        ChannelRole.VENUE,
        Content.subtitle("Not allowed", 0, SubtitleStyle(), "#00FF00"),
    )
    assert state.take(ChannelRole.VENUE)[0] is False
    assert state.venue.live_content.kind is ContentType.BLACK


def test_take_both_is_atomic_on_not_ready(tmp_path: Path) -> None:
    path = tmp_path / "page.pdf"
    path.write_bytes(b"pdf marker")
    state = ApplicationState()
    content = Content.pdf(path, 0)
    state.set_preview(ChannelRole.BROADCAST, content, ready=True)
    state.set_preview(ChannelRole.VENUE, content, ready=False)
    before = (state.broadcast.live_content, state.venue.live_content)
    succeeded, _ = state.take_both()
    assert not succeeded
    assert (state.broadcast.live_content, state.venue.live_content) == before


def test_take_both_commits_both_after_validation(tmp_path: Path) -> None:
    path = tmp_path / "page.pdf"
    path.write_bytes(b"pdf marker")
    state = ApplicationState()
    content = Content.pdf(path, 3)
    state.set_preview(ChannelRole.BROADCAST, content)
    state.set_preview(ChannelRole.VENUE, content)
    assert state.take_both() == (True, "")
    assert state.broadcast.live_content == content
    assert state.venue.live_content == content


def test_black_all_is_shutdown_safe() -> None:
    state = ApplicationState()
    subtitle = Content.subtitle("Live", 0, SubtitleStyle(), "#00FF00")
    state.set_preview(ChannelRole.BROADCAST, subtitle)
    state.take(ChannelRole.BROADCAST)
    state.black_all()
    assert state.broadcast.preview_content.kind is ContentType.BLACK
    assert state.broadcast.live_content.kind is ContentType.BLACK
    assert state.venue.preview_content.kind is ContentType.BLACK
    assert state.venue.live_content.kind is ContentType.BLACK


def test_solid_color_round_trip_and_take() -> None:
    content = Content.solid_color("#00ff00")
    assert content.kind is ContentType.SOLID_COLOR
    assert content.background_color == "#00FF00"
    assert Content.from_dict(content.to_dict()) == content
    assert Content.from_preset_dict(content.to_preset_dict()) == content

    state = ApplicationState()
    state.set_preview(ChannelRole.VENUE, content)
    assert state.venue.live_content.kind is ContentType.BLACK
    assert state.take(ChannelRole.VENUE) == (True, "")
    assert state.venue.live_content == content


def test_bible_reference_layer_round_trips_independently() -> None:
    body_style = SubtitleStyle(font_size=64, y_ratio=0.8)
    reference_style = default_bible_reference_style()
    content = Content.subtitle(
        "본문",
        0,
        body_style,
        "#00FF00",
        source="bible",
        reference="JHN.3.16",
        label="요한복음 3:16",
        label_style=reference_style,
    )

    restored = Content.from_dict(content.to_dict())

    assert restored.text == "본문"
    assert restored.subtitle_style == body_style
    assert restored.subtitle_label == "요한복음 3:16"
    assert restored.subtitle_label_style == reference_style
