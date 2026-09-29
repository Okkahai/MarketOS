"""Portfolio performance from stored snapshots, shared by the Analytics API and backtests."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.market.compute import INTERVAL, PRIMARY_PROVIDER
from app.market.repository import get_bars
from app.models import Asset, PortfolioSnapshot

BENCHMARKS = ("SPY", "BTC-USD")


def daily_values(snaps: list[PortfolioSnapshot]) -> list[tuple[datetime, float]]:
    """Last complete snapshot of each UTC day."""
    by_day: dict[Any, tuple[datetime, float]] = {}
    for s in snaps:
        if s.complete and s.total_value is not None:
            by_day[s.as_of.date()] = (s.as_of, float(s.total_value))
    return [by_day[d] for d in sorted(by_day)]


def close_at(session: Session, symbol: str, ts: datetime) -> float | None:
    """Latest daily close known at ts."""
    asset = session.scalar(select(Asset).where(Asset.symbol == symbol))
    if asset is None:
        return None
    bars = get_bars(session, asset.id, INTERVAL, PRIMARY_PROVIDER[asset.asset_class], ts, 1)
    return float(bars[-1].close) if bars else None


def performance(
    session: Session, snaps: list[PortfolioSnapshot]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(portfolio metrics, benchmark returns over the same window)."""
    daily = daily_values(snaps)
    values = [v for _, v in daily]
    rets = metrics.daily_returns(values)
    portfolio = {
        "days": len(values), "start": daily[0][0] if daily else None,
        "end": daily[-1][0] if daily else None,
        "start_value": values[0] if values else None, "end_value": values[-1] if values else None,
        "return_pct": metrics.total_return_pct(values),
        "max_drawdown_pct": metrics.max_drawdown_pct(values),
        "sharpe": metrics.sharpe(rets), "sortino": metrics.sortino(rets),
        "incomplete_snapshots": sum(1 for s in snaps if not s.complete),
    }  # fmt: skip
    benchmarks = []
    for sym in BENCHMARKS:
        ret = None
        if len(daily) >= 2:
            a, b = close_at(session, sym, daily[0][0]), close_at(session, sym, daily[-1][0])
            ret = (b / a - 1) * 100 if a and b else None
        benchmarks.append({"symbol": sym, "return_pct": ret})
    benchmarks.append({"symbol": "CASH", "return_pct": 0.0 if len(daily) >= 2 else None})
    return portfolio, benchmarks
