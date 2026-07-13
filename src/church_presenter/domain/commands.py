"""Names for application actions used by UI adapters and future hardware adapters."""

from enum import StrEnum


class CommandName(StrEnum):
    TAKE_BROADCAST = "take_broadcast"
    TAKE_VENUE = "take_venue"
    TAKE_BOTH = "take_both"
    BLACK_ALL = "black_all"
