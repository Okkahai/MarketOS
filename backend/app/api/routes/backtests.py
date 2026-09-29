"""Read-only view of backtest runs. They live in their own portfolios and never appear on the
live pages."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.portfolio import SnapshotOut, TradeOut
from app.db.session import get_db
from app.models import Asset, BacktestRun, Portfolio, PortfolioSnapshot, Trade

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])
Db = Annotated[Session, Depends(get_db)]


class BacktestOut(BaseModel):
    id: str
    name: str
    status: str
    start_at: datetime
    end_at: datetime
    step_hours: int
    initial_capital: Decimal
    summary: dict[str, Any] | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class BacktestDetail(BacktestOut):
    params: dict[str, Any]
    snapshots: list[SnapshotOut]


def _out(r: BacktestRun) -> dict[str, Any]:
    return dict(
        id=str(r.id), name=r.name, status=r.status, start_at=r.start_at, end_at=r.end_at,
        step_hours=r.step_hours, initial_capital=r.initial_capital, summary=r.summary,
        error=r.error, started_at=r.started_at, finished_at=r.finished_at,
    )  # fmt: skip


@router.get("", response_model=list[BacktestOut])
def list_runs(session: Db, limit: Annotated[int, Query(ge=1, le=100)] = 30):
    runs = session.scalars(select(BacktestRun).order_by(BacktestRun.started_at.desc()).limit(limit))
    return [BacktestOut(**_out(r)) for r in runs]


@router.get("/{run_id}", response_model=BacktestDetail)
def get_run(run_id: UUID, session: Db) -> BacktestDetail:
    r = session.get(BacktestRun, run_id)
    if r is None:
        raise HTTPException(404, "backtest not found")
    snaps = session.scalars(
        select(PortfolioSnapshot)
        .join(Portfolio, Portfolio.id == PortfolioSnapshot.portfolio_id)
        .where(Portfolio.backtest_run_id == r.id)
        .order_by(PortfolioSnapshot.as_of)
    ).all()
    return BacktestDetail(
        **_out(r), params=r.params,
        snapshots=[
            SnapshotOut(as_of=s.as_of, cash=s.cash, positions_value=s.positions_value,
                        total_value=s.total_value, complete=s.complete)
            for s in snaps
        ],
    )  # fmt: skip


@router.get("/{run_id}/trades", response_model=list[TradeOut])
def run_trades(run_id: UUID, session: Db, limit: Annotated[int, Query(ge=1, le=500)] = 200):
    rows = session.execute(
        select(Trade, Asset.symbol)
        .join(Asset, Asset.id == Trade.asset_id)
        .join(Portfolio, Portfolio.id == Trade.portfolio_id)
        .where(Portfolio.backtest_run_id == run_id)
        .order_by(Trade.seq)
        .limit(limit)
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
