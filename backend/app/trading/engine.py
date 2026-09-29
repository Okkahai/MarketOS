"""The paper trading cycle: exits, decisions, fills, snapshot. Simulation only.

Fill rule (no lookahead): an order made at time t fills at the open of the first bar that opens
after t and is already available. Nothing is filled at a guess; an order with no such bar waits
and then expires.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.core.config import Settings
from app.core.money import quantize_quantity
from app.jobs.runner import run_job
from app.market.compute import INTERVAL, PRIMARY_PROVIDER
from app.models import (
    Asset,
    MarketPrice,
    Order,
    Portfolio,
    PortfolioSnapshot,
    RiskDecision,
    Signal,
)
from app.trading.execute import execute_order
from app.trading.risk import SignalView, evaluate
from app.trading.rules import (
    ENGINE_VERSION,
    QUANTITY_PLACES,
    RiskConfig,
    fill_interval,
    session_open,
    stop_fill,
    target_fill,
)
from app.trading.state import ensure_portfolio, load_state, open_positions, valuation

logger = logging.getLogger(__name__)
SNAPSHOT_EVERY = timedelta(minutes=55)


@dataclass
class Tally:
    decided: int = 0
    approved: int = 0
    rejected: int = 0
    filled: int = 0
    expired: int = 0
    exits: int = 0
    snapshot: bool = False


def bars_after(
    session: Session, asset: Asset, interval: str, after: datetime, now: datetime, limit: int
) -> list[MarketPrice]:
    """Bars (latest revision known at `now`) that open strictly after `after`, oldest first."""
    floor = after if asset.asset_class == "crypto" else after - timedelta(days=2)
    rows = session.scalars(
        select(MarketPrice)
        .where(
            MarketPrice.asset_id == asset.id,
            MarketPrice.interval == interval,
            MarketPrice.provider == PRIMARY_PROVIDER[asset.asset_class],
            MarketPrice.available_at <= now,
            MarketPrice.ts >= floor,
        )
        .distinct(MarketPrice.ts)
        .order_by(MarketPrice.ts, MarketPrice.revision.desc())
        .limit(limit + 3)
    ).all()
    return [b for b in rows if session_open(b.ts, asset.asset_class) > after][:limit]


def decide(
    session: Session, portfolio: Portfolio, cfg: RiskConfig, now: datetime, t: Tally
) -> None:
    decided = exists().where(
        RiskDecision.signal_id == Signal.id, RiskDecision.portfolio_id == portfolio.id
    )
    signals = session.scalars(
        select(Signal)
        .where(
            Signal.mode == "live_paper",
            Signal.generated_at >= portfolio.created_at,
            Signal.generated_at <= now,
            ~decided,
        )
        .order_by(Signal.generated_at, Signal.id)
    ).all()
    for sig in signals:
        asset = session.get(Asset, sig.asset_id)
        assert asset is not None
        state = load_state(session, portfolio, cfg, now)
        view = SignalView(
            sig.action, sig.confidence, str(asset.id), asset.asset_class, asset.sector,
            sig.reference_price_ts, sig.suggested_position_size_pct,
            sig.suggested_stop_loss_pct, sig.suggested_take_profit_pct,
        )  # fmt: skip
        v = evaluate(view, state, cfg, now)
        decision = RiskDecision(
            signal_id=sig.id, portfolio_id=portfolio.id, decision=v.decision,
            reasons=v.reasons, rules_evaluated=v.rules, requested_notional=v.requested,
            approved_notional=v.notional, portfolio_state=state.summary(), config=cfg.snapshot(),
            engine_version=ENGINE_VERSION, decided_at=now,
        )  # fmt: skip
        session.add(decision)
        session.flush()
        t.decided += 1
        if v.side is None:
            t.rejected += 1
            continue
        t.approved += 1
        quantity = None
        if v.side == "SELL":
            held = next(p for p, a in open_positions(session, portfolio.id) if a.id == asset.id)
            full = v.fraction == 1
            quantity = held.quantity
            if not full:
                quantity = quantize_quantity(
                    held.quantity * (v.fraction or 0), QUANTITY_PLACES[asset.asset_class]
                )
        session.add(
            Order(
                portfolio_id=portfolio.id,
                asset_id=asset.id,
                signal_id=sig.id,
                decision_id=decision.id,
                side=v.side,
                reason="signal",
                notional=v.notional,
                quantity=quantity,
                stop_loss_pct=v.stop_pct,
                take_profit_pct=v.take_profit_pct,
                signal_time=now,
                expires_at=now + timedelta(hours=cfg.order_expiry_hours),
            )  # fmt: skip
        )
        session.commit()


def fill_pending(
    session: Session, portfolio: Portfolio, cfg: RiskConfig, now: datetime, t: Tally
) -> None:
    orders = session.scalars(
        select(Order)
        .where(Order.portfolio_id == portfolio.id, Order.status == "pending")
        .order_by(Order.created_at, Order.id)
    ).all()
    for order in orders:
        asset = session.get(Asset, order.asset_id)
        assert asset is not None
        bars = bars_after(
            session, asset, fill_interval(cfg, asset.asset_class), order.signal_time, now, 1
        )
        if bars:
            bar = bars[0]
            trade = execute_order(
                session, order, asset, cfg, bar.open, bar.ts,
                session_open(bar.ts, asset.asset_class),
            )  # fmt: skip
            t.filled += trade is not None
            t.expired += trade is None
        elif order.expires_at <= now:
            order.status = "expired"
            session.commit()
            t.expired += 1


def check_exits(
    session: Session, portfolio: Portfolio, cfg: RiskConfig, now: datetime, t: Tally
) -> None:
    """Stop-loss and take-profit on completed daily bars after the last entry. Both hit in one
    bar: the stop wins (the pessimistic reading)."""
    for pos, asset in open_positions(session, portfolio.id):
        if pos.stop_price is None and pos.target_price is None:
            continue
        for bar in bars_after(session, asset, INTERVAL, pos.last_entry_at, now, 400):
            hit = None
            if pos.stop_price is not None:
                ref = stop_fill(bar.open, bar.low, pos.stop_price)
                hit = ("stop_loss", ref) if ref is not None else None
            if hit is None and pos.target_price is not None:
                ref = target_fill(bar.open, bar.high, pos.target_price)
                hit = ("take_profit", ref) if ref is not None else None
            if hit is None:
                continue
            order = Order(
                portfolio_id=portfolio.id, asset_id=asset.id, signal_id=pos.signal_id,
                side="SELL", reason=hit[0], quantity=pos.quantity, signal_time=bar.available_at,
                expires_at=bar.available_at,
            )  # fmt: skip
            session.add(order)
            session.flush()
            trade = execute_order(session, order, asset, cfg, hit[1], bar.ts, bar.available_at)
            t.exits += trade is not None
            break


def take_snapshot(session: Session, portfolio: Portfolio, cfg: RiskConfig, now: datetime) -> bool:
    last = session.scalar(
        select(func.max(PortfolioSnapshot.as_of)).where(
            PortfolioSnapshot.portfolio_id == portfolio.id
        )
    )
    if last is not None and now - last < SNAPSHOT_EVERY:
        return False
    val = valuation(session, portfolio, cfg, now)
    details: list[dict[str, Any]] = [
        {
            "symbol": ln["asset"].symbol,
            "quantity": str(ln["position"].quantity),
            "price": None if ln["price"] is None else str(ln["price"][0]),
            "price_ts": None if ln["price"] is None else ln["price"][1].isoformat(),
            "value": None if ln["value"] is None else str(ln["value"]),
        }
        for ln in val["lines"]
    ]
    session.add(
        PortfolioSnapshot(
            portfolio_id=portfolio.id,
            as_of=now,
            cash=portfolio.cash,
            positions_value=val["positions_value"],
            total_value=val["total_value"],
            complete=val["complete"],
            details={"positions": details},
        )  # fmt: skip
    )
    session.commit()
    return True


def run_paper_cycle(
    session_factory: sessionmaker[Session], settings: Settings, *, clock: Clock | None = None
) -> uuid.UUID:
    clock = clock or LiveClock()
    cfg = RiskConfig.from_settings(settings)
    with run_job(session_factory, "paper_cycle", clock=clock) as ctx:
        now = clock.now()
        t = Tally()
        with session_factory() as session:
            portfolio = ensure_portfolio(session, settings, now)
            check_exits(session, portfolio, cfg, now, t)
            decide(session, portfolio, cfg, now, t)
            fill_pending(session, portfolio, cfg, now, t)
            t.snapshot = take_snapshot(session, portfolio, cfg, now)
        ctx.items_written = t.filled + t.exits
        ctx.details = t.__dict__.copy()
        return ctx.run_id
