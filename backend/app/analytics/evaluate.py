"""Judging past recommendations. For each signal and horizon, once the horizon has fully elapsed,
compare the last price the model saw with the last daily close inside the horizon, using only
bars that were available by now. Written once and never changed; a horizon without enough bars
is retried on the next run, never estimated."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.metrics import direction_correct
from app.core.clock import Clock, LiveClock
from app.jobs.runner import run_job
from app.market.compute import INTERVAL, PRIMARY_PROVIDER
from app.models import Asset, MarketPrice, PerformanceEvaluation, Signal

HORIZON_DAYS = {"1d": 1, "3d": 3, "7d": 7, "30d": 30}
BENCHMARK = {"stock": "SPY", "etf": "SPY", "crypto": "BTC-USD"}
DAY = timedelta(days=1)
GAP_TOLERANCE = timedelta(days=4)  # a long weekend is fine; a longer hole means missing data
PER_RUN = 500
PCT = Decimal("0.0001")


def _bars(session: Session, asset: Asset, after: datetime, until: datetime, now: datetime):
    """Completed daily bars with ts > after and ts + 1 day <= until, known at `now`."""
    return session.scalars(
        select(MarketPrice)
        .where(
            MarketPrice.asset_id == asset.id,
            MarketPrice.interval == INTERVAL,
            MarketPrice.provider == PRIMARY_PROVIDER[asset.asset_class],
            MarketPrice.available_at <= now,
            MarketPrice.ts > after,
            MarketPrice.ts <= until - DAY,
        )
        .distinct(MarketPrice.ts)
        .order_by(MarketPrice.ts, MarketPrice.revision.desc())
    ).all()


def _close_at_or_before(session: Session, asset: Asset, ts: datetime, now: datetime):
    return session.scalars(
        select(MarketPrice)
        .where(
            MarketPrice.asset_id == asset.id,
            MarketPrice.interval == INTERVAL,
            MarketPrice.provider == PRIMARY_PROVIDER[asset.asset_class],
            MarketPrice.available_at <= now,
            MarketPrice.ts <= ts,
        )
        .order_by(MarketPrice.ts.desc(), MarketPrice.revision.desc())
        .limit(1)
    ).first()


def _pct(end: Decimal, start: Decimal) -> Decimal:
    return ((end / start - 1) * 100).quantize(PCT)


def evaluate_one(
    session: Session, sig: Signal, asset: Asset, horizon: str, now: datetime
) -> dict | None:
    until = sig.generated_at + timedelta(days=HORIZON_DAYS[horizon])
    if until > now:
        return None
    bars = _bars(session, asset, sig.reference_price_ts, until, now)
    if not bars or bars[-1].ts + DAY < until - GAP_TOLERANCE:
        return None
    start, end = sig.reference_price, bars[-1].close
    ret = _pct(end, start)
    mfe = max(_pct(max(b.high for b in bars), start), Decimal(0))
    mae = min(_pct(min(b.low for b in bars), start), Decimal(0))
    bench_symbol = BENCHMARK[asset.asset_class]
    bench_ret = excess = None
    bench = session.scalar(select(Asset).where(Asset.symbol == bench_symbol))
    if bench is not None:
        b0 = _close_at_or_before(session, bench, sig.reference_price_ts, now)
        b1 = _close_at_or_before(session, bench, bars[-1].ts, now)
        if b0 and b1 and b0.close > 0:
            bench_ret = _pct(b1.close, b0.close)
            excess = ret - bench_ret
    correct = direction_correct(sig.action, float(ret))
    return dict(
        signal_id=sig.id, horizon=horizon, evaluated_at=now, start_price=start, end_price=end,
        end_price_ts=bars[-1].ts, return_pct=ret, mfe_pct=mfe, mae_pct=mae,
        benchmark_symbol=bench_symbol, benchmark_return_pct=bench_ret, excess_return_pct=excess,
        direction_correct=correct,
    )  # fmt: skip


def run_evaluate_signals(
    session_factory: sessionmaker[Session], *, clock: Clock | None = None
) -> uuid.UUID:
    clock = clock or LiveClock()
    with run_job(session_factory, "evaluate_signals", clock=clock) as ctx:
        now = clock.now()
        written = waiting = 0
        with session_factory() as session:
            done = {
                (s, h) for s, h in session.execute(
                    select(PerformanceEvaluation.signal_id, PerformanceEvaluation.horizon)
                )
            }  # fmt: skip
            rows = session.execute(
                select(Signal, Asset)
                .join(Asset, Asset.id == Signal.asset_id)
                .where(Signal.mode == "live_paper", Signal.generated_at <= now - DAY)
                .order_by(Signal.generated_at)
                .limit(PER_RUN)
            ).all()
            for sig, asset in rows:
                for horizon in HORIZON_DAYS:
                    if (sig.id, horizon) in done:
                        continue
                    values = evaluate_one(session, sig, asset, horizon, now)
                    if values is None:
                        waiting += 1
                        continue
                    session.execute(
                        insert(PerformanceEvaluation)
                        .values(**values)
                        .on_conflict_do_nothing(index_elements=["signal_id", "horizon"])
                    )
                    written += 1
            session.commit()
        ctx.items_written = written
        ctx.details = {"written": written, "not_ready": waiting}
        return ctx.run_id
