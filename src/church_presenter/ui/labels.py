from __future__ import annotations

from church_presenter.domain.enums import ChannelRole


def channel_label(role: ChannelRole) -> str:
    """Return the Korean operator-facing label for an output channel."""
    return "송출" if role is ChannelRole.BROADCAST else "현장"
