"""Compute indicators from point-in-time bars and store the newest values."""

import math
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.core.config import Settings
from app.jobs.runner import run_job
from app.market.indicators import compute_indicators
from app.market.repository import get_bars
from app.models import Asset, IndicatorValue

CODE_VERSION = "1"
LOOKBACK_BARS = 400  # enough for the 200-bar SMA with room to spare
INTERVAL = "1d"
PRIMARY_PROVIDER = {"stock": "tiingo", "etf": "tiingo", "crypto": "coinbase"}
# Relative strength and correlation are measured against one benchmark per asset class.
BENCHMARK_SYMBOL = {"stock": "SPY", "etf": "SPY", "crypto": "BTC-USD"}
_PLACES = Decimal("1e-10")


def compute_asset(
    session: Session, asset: Asset, bench: Asset | None, as_of: datetime, store_last: int
) -> int:
    provider = PRIMARY_PROVIDER[asset.asset_class]
    bars = get_bars(session, asset.id, INTERVAL, provider, as_of, LOOKBACK_BARS)
    if not bars:
        return 0
    bench_closes: dict[datetime, float] | None = None
    if bench is not None and bench.id != asset.id:
        bench_bars = get_bars(
            session, bench.id, INTERVAL, PRIMARY_PROVIDER[bench.asset_class], as_of, LOOKBACK_BARS
        )
        bench_closes = {b.ts: float(b.close) for b in bench_bars}

    series = compute_indicators(
        [b.ts for b in bars],
        [float(b.high) for b in bars],
        [float(b.low) for b in bars],
        [float(b.close) for b in bars],
        [float(b.volume) for b in bars],
        bench_closes,
    )
    known_at = max(b.available_at for b in bars)
    rows = []
    for name, values in series.items():
        for i in range(max(0, len(bars) - store_last), len(bars)):
            v = values[i]
            if v is None or not math.isfinite(v):
                continue
            rows.append(
                {
                    "asset_id": asset.id, "interval": INTERVAL, "ts": bars[i].ts, "name": name,
                    "value": Decimal(repr(v)).quantize(_PLACES), "params": {},
                    "computed_from_available_at": known_at, "code_version": CODE_VERSION,
                }
            )  # fmt: skip
    if rows:
        stmt = insert(IndicatorValue).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_indicator_values_point",
                set_={
                    "value": stmt.excluded.value,
                    "computed_from_available_at": stmt.excluded.computed_from_available_at,
                },
            )
        )
        session.commit()
    return len(rows)


def run_compute_indicators(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    clock: Clock | None = None,
) -> uuid.UUID:
    clock = clock or LiveClock()
    with run_job(session_factory, "compute_indicators", clock=clock) as ctx:
        with session_factory() as session:
            assets = session.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
            by_symbol = {a.symbol: a for a in assets}
            total = 0
            per_asset: dict[str, int] = {}
            for asset in assets:
                bench = by_symbol.get(BENCHMARK_SYMBOL[asset.asset_class])
                n = compute_asset(session, asset, bench, clock.now(), settings.indicator_store_bars)
                per_asset[asset.symbol] = n
                total += n
        ctx.items_written = total
        ctx.details = {"interval": INTERVAL, "assets": per_asset}
        return ctx.run_id
