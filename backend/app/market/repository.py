"""Reading and writing raw bars. Reads are point-in-time: only what was available at as_of."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.market.bars import Bar
from app.models import MarketPrice


def get_bars(
    session: Session,
    asset_id: uuid.UUID,
    interval: str,
    provider: str,
    as_of: datetime,
    limit: int,
) -> list[MarketPrice]:
    """The newest `limit` bars known at as_of, oldest first.

    When a bar was revised, the revision that was available at as_of wins, so a backtest never
    sees a correction that had not been published yet.
    """
    query = (
        select(MarketPrice)
        .where(
            MarketPrice.asset_id == asset_id,
            MarketPrice.interval == interval,
            MarketPrice.provider == provider,
            MarketPrice.available_at <= as_of,
        )
        .distinct(MarketPrice.ts)
        .order_by(MarketPrice.ts.desc(), MarketPrice.revision.desc())
        .limit(limit)
    )
    return list(reversed(session.scalars(query).all()))


@dataclass(frozen=True, slots=True)
class StoreStats:
    written: int = 0
    revisions: int = 0
    unchanged: int = 0
    not_yet_available: int = 0


def latest_stored_ts(
    session: Session, asset_id: uuid.UUID, interval: str, provider: str
) -> datetime | None:
    return session.scalar(
        select(func.max(MarketPrice.ts)).where(
            MarketPrice.asset_id == asset_id,
            MarketPrice.interval == interval,
            MarketPrice.provider == provider,
        )
    )


def store_bars(
    session: Session,
    *,
    asset_id: uuid.UUID,
    interval: str,
    provider: str,
    bars: list[Bar],
    run_id: uuid.UUID | None,
    now: datetime,
) -> StoreStats:
    """Insert new bars and new revisions of changed bars. Never updates a stored row.

    A bar whose available_at is still in the future is skipped: it is either in progress or
    not yet final at the provider, and using it would be lookahead.
    """
    ready = [b for b in bars if b.available_at <= now]
    if not ready:
        return StoreStats(not_yet_available=len(bars))

    existing = {
        row.ts: row
        for row in session.scalars(
            select(MarketPrice)
            .where(
                MarketPrice.asset_id == asset_id,
                MarketPrice.interval == interval,
                MarketPrice.provider == provider,
                MarketPrice.ts >= min(b.ts for b in ready),
                MarketPrice.ts <= max(b.ts for b in ready),
            )
            .distinct(MarketPrice.ts)
            .order_by(MarketPrice.ts, MarketPrice.revision.desc())
        )
    }

    rows: list[dict] = []
    revisions = unchanged = 0
    for bar in ready:
        previous = existing.get(bar.ts)
        if previous is None:
            revision, available_at = 0, bar.available_at
        elif _same(previous, bar):
            unchanged += 1
            continue
        else:
            # The corrected values only became known now.
            revision, available_at = previous.revision + 1, max(now, bar.available_at)
            revisions += 1
        rows.append(
            {
                "asset_id": asset_id, "interval": interval, "ts": bar.ts, "open": bar.open,
                "high": bar.high, "low": bar.low, "close": bar.close, "adj_close": bar.adj_close,
                "volume": bar.volume, "provider": provider, "available_at": available_at,
                "revision": revision, "run_id": run_id,
            }
        )  # fmt: skip
    if rows:
        # A concurrent run inserting the same bar is harmless: the unique key drops the duplicate.
        session.execute(insert(MarketPrice).values(rows).on_conflict_do_nothing())
    session.commit()
    return StoreStats(
        written=len(rows) - revisions,
        revisions=revisions,
        unchanged=unchanged,
        not_yet_available=len(bars) - len(ready),
    )


def _same(stored: MarketPrice, bar: Bar) -> bool:
    fields = ("open", "high", "low", "close", "volume", "adj_close")
    return all(getattr(stored, f) == getattr(bar, f) for f in fields)
