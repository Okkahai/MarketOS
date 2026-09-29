"""Read-only performance numbers: the portfolio against SPY, BTC and cash, closed-trade
statistics, and how the AI's recommendations did afterwards, wrong ones included."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.db.session import get_db
from app.market.compute import INTERVAL, PRIMARY_PROVIDER
from app.market.repository import get_bars
from app.models import (
    Asset,
    PerformanceEvaluation,
    Portfolio,
    PortfolioSnapshot,
    Position,
    Signal,
)
from app.trading.state import PORTFOLIO_NAME

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
Db = Annotated[Session, Depends(get_db)]
BENCHMARKS = ("SPY", "BTC-USD")
NOTES = (
    "Daily returns, 365 days a year, risk-free rate 0. Snapshots with a missing price are skipped."
)


class ClosedPosition(BaseModel):
    symbol: str
    realized_pnl: float
    opened_at: datetime
    closed_at: datetime
    signal_id: str


class EvaluationOut(BaseModel):
    signal_id: str
    symbol: str
    action: str
    horizon: str
    generated_at: datetime
    start_price: float
    end_price: float
    return_pct: float
    mfe_pct: float
    mae_pct: float
    benchmark_symbol: str | None
    excess_return_pct: float | None
    direction_correct: bool | None


class SummaryOut(BaseModel):
    portfolio: dict[str, Any]
    benchmarks: list[dict[str, Any]]
    trades: dict[str, Any]
    closed_positions: list[ClosedPosition]
    predictions: list[dict[str, Any]]
    notes: str


def _daily_values(snaps: list[PortfolioSnapshot]) -> list[tuple[datetime, float]]:
    """Last complete snapshot of each UTC day."""
    by_day: dict[Any, tuple[datetime, float]] = {}
    for s in snaps:
        if s.complete and s.total_value is not None:
            by_day[s.as_of.date()] = (s.as_of, float(s.total_value))
    return [by_day[d] for d in sorted(by_day)]


def _close_at(session: Session, symbol: str, ts: datetime) -> float | None:
    asset = session.scalar(select(Asset).where(Asset.symbol == symbol))
    if asset is None:
        return None
    bars = get_bars(session, asset.id, INTERVAL, PRIMARY_PROVIDER[asset.asset_class], ts, 1)
    return float(bars[-1].close) if bars else None


@router.get("/summary", response_model=SummaryOut)
def summary(session: Db) -> SummaryOut:
    p = session.scalar(select(Portfolio).where(Portfolio.name == PORTFOLIO_NAME))
    daily: list[tuple[datetime, float]] = []
    incomplete = 0
    if p:
        snaps = session.scalars(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.portfolio_id == p.id)
            .order_by(PortfolioSnapshot.as_of)
        ).all()
        incomplete = sum(1 for s in snaps if not s.complete)
        daily = _daily_values(list(snaps))
    values = [v for _, v in daily]
    rets = metrics.daily_returns(values)
    portfolio = {
        "days": len(values), "start": daily[0][0] if daily else None,
        "end": daily[-1][0] if daily else None,
        "start_value": values[0] if values else None, "end_value": values[-1] if values else None,
        "return_pct": metrics.total_return_pct(values),
        "max_drawdown_pct": metrics.max_drawdown_pct(values),
        "sharpe": metrics.sharpe(rets), "sortino": metrics.sortino(rets),
        "incomplete_snapshots": incomplete,
    }  # fmt: skip

    benchmarks = []
    for sym in BENCHMARKS:
        ret = None
        if len(daily) >= 2:
            a, b = _close_at(session, sym, daily[0][0]), _close_at(session, sym, daily[-1][0])
            ret = (b / a - 1) * 100 if a and b else None
        benchmarks.append({"symbol": sym, "return_pct": ret})
    benchmarks.append({"symbol": "CASH", "return_pct": 0.0 if len(daily) >= 2 else None})

    closed = session.execute(
        select(Position, Asset.symbol)
        .join(Asset, Asset.id == Position.asset_id)
        .where(Position.closed_at.is_not(None))
        .order_by(Position.closed_at.desc())
    ).all()
    closed_out = [
        ClosedPosition(symbol=sym, realized_pnl=float(pos.realized_pnl), opened_at=pos.opened_at,
                       closed_at=pos.closed_at, signal_id=str(pos.signal_id))
        for pos, sym in closed
    ]  # fmt: skip

    evals = session.scalars(select(PerformanceEvaluation)).all()
    predictions = []
    for h in ("1d", "3d", "7d", "30d"):
        rows = [e for e in evals if e.horizon == h]
        judged = [e for e in rows if e.direction_correct is not None]
        excess = [float(e.excess_return_pct) for e in rows if e.excess_return_pct is not None]
        predictions.append({
            "horizon": h, "evaluated": len(rows), "directional": len(judged),
            "hit_rate": sum(e.direction_correct for e in judged) / len(judged) if judged else None,
            "avg_return_pct": sum(float(e.return_pct) for e in rows) / len(rows) if rows else None,
            "avg_excess_pct": sum(excess) / len(excess) if excess else None,
        })  # fmt: skip
    return SummaryOut(
        portfolio=portfolio, benchmarks=benchmarks,
        trades=metrics.trade_stats([c.realized_pnl for c in closed_out]),
        closed_positions=closed_out[:50], predictions=predictions, notes=NOTES,
    )  # fmt: skip


@router.get("/evaluations", response_model=list[EvaluationOut])
def evaluations(
    session: Db,
    horizon: Annotated[str | None, Query(pattern="^(1d|3d|7d|30d)$")] = None,
    wrong_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EvaluationOut]:
    q = (
        select(PerformanceEvaluation, Signal, Asset.symbol)
        .join(Signal, Signal.id == PerformanceEvaluation.signal_id)
        .join(Asset, Asset.id == Signal.asset_id)
        .order_by(Signal.generated_at.desc(), PerformanceEvaluation.horizon)
        .limit(limit)
    )
    if horizon:
        q = q.where(PerformanceEvaluation.horizon == horizon)
    if wrong_only:
        q = q.where(PerformanceEvaluation.direction_correct.is_(False))
    return [
        EvaluationOut(
            signal_id=str(s.id),
            symbol=sym,
            action=s.action,
            horizon=e.horizon,
            generated_at=s.generated_at,
            start_price=float(e.start_price),
            end_price=float(e.end_price),
            return_pct=float(e.return_pct),
            mfe_pct=float(e.mfe_pct),
            mae_pct=float(e.mae_pct),
            benchmark_symbol=e.benchmark_symbol,
            excess_return_pct=None if e.excess_return_pct is None else float(e.excess_return_pct),
            direction_correct=e.direction_correct,
        )  # fmt: skip
        for e, s, sym in session.execute(q)
    ]
