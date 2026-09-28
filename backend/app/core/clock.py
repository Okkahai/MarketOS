"""Time source abstraction.

Services take a Clock instead of calling datetime.now() so the same code can run
live or replay history in a backtest without seeing the future.
"""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class LiveClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that only moves when told to. Used by tests and backtest replay."""

    def __init__(self, start: datetime) -> None:
        self._now = ensure_utc(start)

    def now(self) -> datetime:
        return self._now

    def advance_to(self, when: datetime) -> None:
        when = ensure_utc(when)
        if when < self._now:
            raise ValueError("a replay clock cannot move backwards")
        self._now = when


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalise aware ones to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: every timestamp must carry a timezone")
    return value.astimezone(UTC)
