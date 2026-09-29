from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.clock import FixedClock, LiveClock, ensure_utc
from app.core.ids import uuid7


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 9, 28, 12, 0))  # noqa: DTZ001


def test_aware_datetime_is_normalised_to_utc():
    istanbul = timezone(timedelta(hours=3))
    value = ensure_utc(datetime(2026, 9, 28, 15, 0, tzinfo=istanbul))
    assert value == datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    assert value.utcoffset() == timedelta(0)


def test_live_clock_is_utc():
    assert LiveClock().now().utcoffset() == timedelta(0)


def test_replay_clock_cannot_move_backwards():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FixedClock(start)
    clock.advance_to(start + timedelta(days=1))
    assert clock.now() == start + timedelta(days=1)
    with pytest.raises(ValueError):
        clock.advance_to(start)


def test_uuid7_version_variant_and_time_order():
    first = uuid7()
    later = [uuid7() for _ in range(50)]
    assert first.version == 7
    assert first.variant == "specified in RFC 4122"
    # Leading 48 bits are the millisecond timestamp, so ids never go back in time.
    assert all((u.int >> 80) >= (first.int >> 80) for u in later)
