"""Read-only view of the paper portfolio: holdings, trades, risk verdicts, orders, value history."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import LiveClock
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    Asset,
    Order,
    Portfolio,
    PortfolioSnapshot,
    RiskDecision,
    Signal,
    Trade,
)
from app.trading.rules import RiskConfig
from app.trading.state import PORTFOLIO_NAME, load_state, valuation

router = APIRouter(prefix="/api/v1", tags=["portfolio"])
Db = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=200)]


class PositionOut(BaseModel):
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    cost_basis: Decimal
    price: Decimal | None
    price_ts: datetime | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal
    stop_price: Decimal | None
    target_price: Decimal | None
    opened_at: datetime
    signal_id: str


class PortfolioOut(BaseModel):
    name: str
    mode: str
    starting_capital: Decimal
    cash: Decimal
    positions_value: Decimal | None
    total_value: Decimal | None
    peak_value: Decimal
    drawdown_pct: Decimal | None
    realized_pnl: Decimal
    complete: bool
    positions: list[PositionOut]


class TradeOut(BaseModel):
    id: str
    symbol: str
    side: str
    reason: str
    quantity: Decimal
    reference_price: Decimal
    price: Decimal
    slippage_bps: Decimal
    fee: Decimal
    cash_change: Decimal
    realized_pnl: Decimal
    executed_at: datetime
    price_ts: datetime
    signal_id: str


class DecisionOut(BaseModel):
    id: str
    signal_id: str
    symbol: str
    action: str
    confidence: Decimal
    decision: str
    reasons: list[str]
    rules_evaluated: list[dict]
    requested_notional: Decimal | None
    approved_notional: Decimal | None
    decided_at: datetime


class OrderOut(BaseModel):
    id: str
    symbol: str
    side: str
    reason: str
    status: str
    notional: Decimal | None
    quantity: Decimal | None
    signal_time: datetime
    expires_at: datetime
    filled_at: datetime | None
    signal_id: str


class SnapshotOut(BaseModel):
    as_of: datetime
    cash: Decimal
    positions_value: Decimal | None
    total_value: Decimal | None
    complete: bool


def _portfolio(session: Session) -> Portfolio:
    p = session.scalar(select(Portfolio).where(Portfolio.name == PORTFOLIO_NAME))
    if p is None:
        raise HTTPException(404, "no paper portfolio yet: the first paper cycle creates it")
    return p


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(session: Db) -> PortfolioOut:
    p = _portfolio(session)
    cfg = RiskConfig.from_settings(get_settings())
    now = LiveClock().now()
    val = valuation(session, p, cfg, now)
    state = load_state(session, p, cfg, now)
    realized = session.scalar(select(func.coalesce(func.sum(Trade.realized_pnl), 0)).where(
        Trade.portfolio_id == p.id
    ))  # fmt: skip
    positions = []
    for ln in val["lines"]:
        pos, asset = ln["position"], ln["asset"]
        price = ln["price"]
        positions.append(
            PositionOut(
                symbol=asset.symbol,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                cost_basis=pos.cost_basis,
                price=price and price[0],
                price_ts=price and price[1],
                market_value=ln["value"],
                unrealized_pnl=None if ln["value"] is None else ln["value"] - pos.cost_basis,
                realized_pnl=pos.realized_pnl,
                stop_price=pos.stop_price,
                target_price=pos.target_price,
                opened_at=pos.opened_at,
                signal_id=str(pos.signal_id),
            )  # fmt: skip
        )
    total = val["total_value"]
    drawdown = None
    if total is not None and state.peak_equity > 0:
        drawdown = ((state.peak_equity - total) / state.peak_equity * 100).quantize(Decimal("0.01"))
    return PortfolioOut(
        name=p.name, mode=p.mode, starting_capital=p.starting_capital, cash=p.cash,
        positions_value=val["positions_value"], total_value=total,
        peak_value=state.peak_equity, drawdown_pct=drawdown, realized_pnl=realized,
        complete=val["complete"], positions=positions,
    )  # fmt: skip


@router.get("/trades", response_model=list[TradeOut])
def list_trades(session: Db, limit: Limit = 50, offset: Annotated[int, Query(ge=0)] = 0):
    rows = session.execute(
        select(Trade, Asset.symbol)
        .join(Asset, Asset.id == Trade.asset_id)
        .order_by(Trade.seq.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        TradeOut(
            id=str(t.id),
            symbol=sym,
            side=t.side,
            reason=t.reason,
            quantity=t.quantity,
            reference_price=t.reference_price,
            price=t.price,
            slippage_bps=t.slippage_bps,
            fee=t.fee,
            cash_change=t.cash_change,
            realized_pnl=t.realized_pnl,
            executed_at=t.executed_at,
            price_ts=t.price_ts,
            signal_id=str(t.signal_id),
        )  # fmt: skip
        for t, sym in rows
    ]


@router.get("/risk-decisions", response_model=list[DecisionOut])
def list_decisions(
    session: Db,
    decision: Literal["approved", "reduced", "rejected"] | None = None,
    limit: Limit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    q = (
        select(RiskDecision, Signal, Asset.symbol)
        .join(Signal, Signal.id == RiskDecision.signal_id)
        .join(Asset, Asset.id == Signal.asset_id)
        .order_by(RiskDecision.decided_at.desc(), RiskDecision.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if decision:
        q = q.where(RiskDecision.decision == decision)
    return [
        DecisionOut(
            id=str(d.id),
            signal_id=str(d.signal_id),
            symbol=sym,
            action=s.action,
            confidence=s.confidence,
            decision=d.decision,
            reasons=d.reasons,
            rules_evaluated=d.rules_evaluated,
            requested_notional=d.requested_notional,
            approved_notional=d.approved_notional,
            decided_at=d.decided_at,
        )  # fmt: skip
        for d, s, sym in session.execute(q)
    ]


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    session: Db, status: Literal["pending", "filled", "expired"] | None = None, limit: Limit = 50
):
    q = (
        select(Order, Asset.symbol)
        .join(Asset, Asset.id == Order.asset_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Order.status == status)
    return [
        OrderOut(
            id=str(o.id),
            symbol=sym,
            side=o.side,
            reason=o.reason,
            status=o.status,
            notional=o.notional,
            quantity=o.quantity,
            signal_time=o.signal_time,
            expires_at=o.expires_at,
            filled_at=o.filled_at,
            signal_id=str(o.signal_id),
        )  # fmt: skip
        for o, sym in session.execute(q)
    ]


@router.get("/portfolio/snapshots", response_model=list[SnapshotOut])
def list_snapshots(session: Db, limit: Annotated[int, Query(ge=1, le=2000)] = 500):
    p = _portfolio(session)
    rows = session.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == p.id)
        .order_by(PortfolioSnapshot.as_of.desc())
        .limit(limit)
    ).all()
    return [
        SnapshotOut(as_of=r.as_of, cash=r.cash, positions_value=r.positions_value,
                    total_value=r.total_value, complete=r.complete)
        for r in reversed(rows)
    ]  # fmt: skip
