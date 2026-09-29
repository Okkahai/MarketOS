"""Reading the portfolio: marks, holdings, and the state the risk engine judges."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.money import quantize_money
from app.market.compute import INTERVAL, PRIMARY_PROVIDER
from app.market.repository import get_bars
from app.models import (
    Asset,
    CashLedger,
    Order,
    Portfolio,
    PortfolioSnapshot,
    Position,
    Trade,
)
from app.trading.risk import Holding, Pending, PortfolioState
from app.trading.rules import RiskConfig, fill_interval

PORTFOLIO_NAME = "main"
ZERO = Decimal(0)


def ensure_portfolio(session: Session, settings: Settings, now: datetime) -> Portfolio:
    """The one live paper portfolio and its opening deposit. Idempotent."""
    existing = session.scalar(select(Portfolio).where(Portfolio.name == PORTFOLIO_NAME))
    if existing:
        return existing
    capital = quantize_money(Decimal(settings.paper_initial_capital))
    p = Portfolio(name=PORTFOLIO_NAME, starting_capital=capital, cash=capital, created_at=now)
    session.add(p)
    session.flush()
    session.add(
        CashLedger(portfolio_id=p.id, kind="deposit", amount=capital, balance_after=capital)
    )
    session.commit()
    return p


def mark(
    session: Session, asset: Asset, cfg: RiskConfig, as_of: datetime
) -> tuple[Decimal, datetime] | None:
    """Latest close usable at as_of: the fill-interval bar for crypto if fresh, else the daily
    bar. None when there is no price; callers must treat that as incomplete, not zero."""
    provider = PRIMARY_PROVIDER[asset.asset_class]
    for interval in dict.fromkeys((fill_interval(cfg, asset.asset_class), INTERVAL)):
        bars = get_bars(session, asset.id, interval, provider, as_of, 1)
        if bars and as_of - bars[-1].ts <= timedelta(
            hours=cfg.max_price_age_hours(asset.asset_class)
        ):
            return bars[-1].close, bars[-1].ts
    return None


def open_positions(session: Session, portfolio_id: uuid.UUID) -> list[tuple[Position, Asset]]:
    rows = session.execute(
        select(Position, Asset)
        .join(Asset, Asset.id == Position.asset_id)
        .where(Position.portfolio_id == portfolio_id, Position.closed_at.is_(None))
        .order_by(Asset.symbol)
    )
    return [(p, a) for p, a in rows]


def valuation(
    session: Session, portfolio: Portfolio, cfg: RiskConfig, as_of: datetime
) -> dict[str, Any]:
    """Cash plus positions at their marks. Any unpriced position makes the total None."""
    lines, total, complete = [], ZERO, True
    for pos, asset in open_positions(session, portfolio.id):
        m = mark(session, asset, cfg, as_of)
        value = None if m is None else quantize_money(pos.quantity * m[0])
        complete &= value is not None
        total += value or ZERO
        lines.append({"position": pos, "asset": asset, "price": m, "value": value})
    return {
        "lines": lines,
        "positions_value": total if complete else None,
        "total_value": quantize_money(portfolio.cash + total) if complete else None,
        "complete": complete,
    }


def load_state(
    session: Session, portfolio: Portfolio, cfg: RiskConfig, now: datetime
) -> PortfolioState:
    val = valuation(session, portfolio, cfg, now)
    holdings = {
        str(line["asset"].id): Holding(
            str(line["asset"].id),
            line["asset"].sector,
            line["asset"].asset_class,
            line["position"].quantity,
            line["value"] or ZERO,
        )
        for line in val["lines"]
    }
    pending = {
        str(a.id): Pending(n, a.sector, a.asset_class)
        for a, n in session.execute(
            select(Asset, func.sum(Order.notional))
            .join(Order, Order.asset_id == Asset.id)
            .where(
                Order.portfolio_id == portfolio.id,
                Order.status == "pending",
                Order.side == "BUY",
            )
            .group_by(Asset.id)
        )
    }
    last = {
        str(a): t
        for a, t in session.execute(
            select(Trade.asset_id, func.max(Trade.executed_at))
            .where(Trade.portfolio_id == portfolio.id, Trade.executed_at <= now)
            .group_by(Trade.asset_id)
        )
    }
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trades_today = session.scalar(
        select(func.count())
        .select_from(Trade)
        .where(
            Trade.portfolio_id == portfolio.id,
            Trade.executed_at >= day_start,
            Trade.executed_at <= now,
            Trade.reason == "signal",
        )
    )
    peak = session.scalar(
        select(func.max(PortfolioSnapshot.total_value)).where(
            PortfolioSnapshot.portfolio_id == portfolio.id, PortfolioSnapshot.as_of <= now
        )
    )
    total = val["total_value"]
    peak_equity = max(portfolio.starting_capital, peak or ZERO, total or ZERO)
    return PortfolioState(
        portfolio.cash, total, peak_equity, holdings, pending, last, trades_today or 0
    )


def portfolio_view(session: Session, settings: Settings, now: datetime) -> dict[str, Any] | None:
    """What the analyst model and the signal journal see of the portfolio; None if none exists."""
    portfolio = session.scalar(select(Portfolio).where(Portfolio.name == PORTFOLIO_NAME))
    if portfolio is None:
        return None
    cfg = RiskConfig.from_settings(settings)
    state = load_state(session, portfolio, cfg, now)
    equity = state.equity
    return {
        **state.summary(),
        "positions": [
            {
                "symbol": line["asset"].symbol,
                "weight_pct": None
                if equity is None or line["value"] is None
                else str((line["value"] / equity * 100).quantize(Decimal("0.1"))),
                "avg_cost": str(line["position"].avg_cost.quantize(Decimal("0.0001"))),
            }
            for line in valuation(session, portfolio, cfg, now)["lines"]
        ],
    }
