from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.market.bars import Bar, crypto_available_at, stock_daily_available_at

T = datetime(2026, 9, 25, tzinfo=UTC)


def make(**kw):
    base = dict(ts=T, open=D("10"), high=D("12"), low=D("9"), close=D("11"), volume=D("5"),
                available_at=T + timedelta(days=1))  # fmt: skip
    return Bar(**{**base, **kw})


def test_valid_bar():
    assert make().close == D("11")


@pytest.mark.parametrize(
    "bad",
    [
        {"low": D("0")},
        {"low": D("-1")},
        {"high": D("8")},  # high below low
        {"open": D("13")},  # open above high
        {"close": D("8")},  # close below low
        {"volume": D("-1")},
        {"adj_close": D("0")},
    ],
)
def test_invalid_bars_are_rejected(bad):
    with pytest.raises(ValueError):
        make(**bad)


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError):
        make(ts=datetime(2026, 9, 25))  # noqa: DTZ001


def test_stock_daily_bar_is_available_at_8pm_new_york_across_dst():
    # September: EDT (UTC-4) -> 00:00 UTC next day. December: EST (UTC-5) -> 01:00 UTC next day.
    assert stock_daily_available_at(date(2026, 9, 25)) == datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    assert stock_daily_available_at(date(2026, 12, 15)) == datetime(2026, 12, 16, 1, 0, tzinfo=UTC)


def test_crypto_bar_is_available_after_close_plus_grace():
    minute = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    assert crypto_available_at(minute, "1m") == minute + timedelta(minutes=1, seconds=5)
    assert crypto_available_at(minute, "1d") == minute + timedelta(days=1, seconds=5)
