"""Bar value object and the time rules that decide when a bar may be used."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

INTERVAL_DELTA = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}

# Tiingo: "Most US Equity prices are available at 5:30 PM EST, however exchanges may send
# corrections until 8 PM EST." A stock's daily bar is used only after the corrections window.
NEW_YORK = ZoneInfo("America/New_York")
STOCK_DAILY_AVAILABLE_AT = time(20, 0)
# Exchange candles can still receive late trades for a moment after the bar closes.
CRYPTO_CLOSE_GRACE = timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    available_at: datetime
    adj_close: Decimal | None = None

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        if self.low <= 0:
            raise ValueError("prices must be positive")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError("open/close outside the low-high range")
        if self.volume < 0:
            raise ValueError("negative volume")
        if self.adj_close is not None and self.adj_close <= 0:
            raise ValueError("adjusted close must be positive")


@dataclass(frozen=True, slots=True)
class RejectedRow:
    reason: str
    raw: str  # short excerpt of the offending row for the audit trail


@dataclass(slots=True)
class FetchResult:
    bars: list[Bar] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)


def stock_daily_available_at(trading_date: date) -> datetime:
    return datetime.combine(trading_date, STOCK_DAILY_AVAILABLE_AT, tzinfo=NEW_YORK).astimezone(UTC)


def crypto_available_at(ts: datetime, interval: str) -> datetime:
    return ts + INTERVAL_DELTA[interval] + CRYPTO_CLOSE_GRACE
