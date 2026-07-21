from __future__ import annotations

from church_presenter.domain.enums import ContentType

FIXED_OUTPUT_FADE_DURATION_MS = 250


class TransitionService:
    """Policy for inexpensive output fades."""

    def __init__(self, fade_duration_ms: int = FIXED_OUTPUT_FADE_DURATION_MS) -> None:
        self.fade_duration_ms = max(0, min(2000, fade_duration_ms))

    def should_fade(self, previous: ContentType, upcoming: ContentType) -> bool:
        supported = {
            ContentType.BLACK,
            ContentType.SOLID_COLOR,
            ContentType.PDF_PAGE,
            ContentType.VIDEO,
        }
        return (
            self.fade_duration_ms > 0
            and previous is not upcoming
            and previous in supported
            and upcoming in supported
        )
