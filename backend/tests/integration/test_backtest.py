"""Backtests: chronology (nothing from the future is read), isolation, determinism."""

# ruff: noqa: F811, F401  (db fixture and pytestmark are shared from test_trading)
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.backtest.runner import BacktestError, run_backtest
from app.core.clock import FixedClock
from app.core.config import Settings
from app.events.build import run_cluster_events
from app.market.bars import Bar, stock_daily_available_at
from app.market.repository import store_bars
from app.models import (
    Asset,
    BacktestRun,
    Portfolio,
    PortfolioSnapshot,
    Position,
    Signal,
    Trade,
)
from app.news.ingest import run_news_source
from app.news.normalize import NewsFetch, RawArticle
from tests.integration.test_trading import db, pytestmark

DAY0 = datetime(2026, 8, 3, tzinfo=UTC)
START = datetime(2026, 8, 21, 22, tzinfo=UTC)
END = datetime(2026, 9, 10, 22, tzinfo=UTC)
GOOD = "Apple beats estimates and raises guidance, stock surges on strong demand"
LATE_BAD = datetime(2026, 9, 5, 0, 30, tzinfo=UTC)  # when the poisoned bar becomes available


def choppy(db, poison=False, n=45):
    """Closes zig-zag around 100. With poison, Aug 28's bar collapses to 1 but only becomes
    available on Sep 5 (a late correction): a stop hit that must not be seen earlier."""
    bars = []
    for i in range(n):
        ts = DAY0 + timedelta(days=i)
        c = D(100 + (i % 2) * 2)
        low, avail = c - 1, stock_daily_available_at(ts.date())
        if poison and ts == datetime(2026, 8, 28, tzinfo=UTC):
            low, avail = D(1), LATE_BAD
        bars.append(Bar(ts=ts, open=c, high=c + 1, low=low, close=c, volume=D(1000),
                        available_at=avail))  # fmt: skip
    with db() as s:
        asset = s.scalar(select(Asset).where(Asset.symbol == "AAPL"))
        store_bars(s, asset_id=asset.id, interval="1d", provider="tiingo", bars=bars, run_id=None,
                   now=datetime(2026, 9, 20, tzinfo=UTC))  # fmt: skip


def news(db, published, title, n, collected=None):
    """An article published at `published` and stored at `collected` (default: an hour later)."""
    at = collected or published + timedelta(hours=1)
    art = RawArticle(external_id=f"id{n}", url=f"https://news.test/{n}", title=title, summary="",
                     published_at=published, provider_tickers=("aapl",), raw={"source": "wire"})  # fmt: skip  # noqa: E501
    run_news_source(db, Settings(), source_key="tiingo_news", clock=FixedClock(at),
                    fetcher=lambda since: NewsFetch(articles=[art]))  # fmt: skip
    run_cluster_events(db, Settings(), clock=FixedClock(at))


def backtest(db, **kw):
    return run_backtest(db, Settings(), start=START, end=END, **kw)


def rows(db, model, *order):
    with db() as s:
        return list(s.scalars(select(model).order_by(*order)))


def trade_key(t):
    return (t.side, t.reason, str(t.quantity), str(t.price), t.executed_at)


def test_refuses_claude_and_bad_windows(db):
    with pytest.raises(BacktestError, match="rules"):
        run_backtest(db, Settings(ai_provider="anthropic"), start=START, end=END)
    with pytest.raises(BacktestError, match="past"):
        run_backtest(db, Settings(), start=END, end=START)
    with pytest.raises(BacktestError, match="past"):
        run_backtest(db, Settings(), start=START, end=datetime(2099, 1, 1, tzinfo=UTC))


def test_replay_trades_the_news_in_its_own_portfolio_and_leaves_live_untouched(db):
    choppy(db)
    news(db, datetime(2026, 8, 25, 12, tzinfo=UTC), GOOD, 1)
    run_id = backtest(db)

    (run,) = rows(db, BacktestRun)
    assert run.id == run_id and run.status == "succeeded" and run.summary["steps"] == 21
    assert run.summary["signals_journalled"] >= 1 and run.summary["trade_count"] >= 1
    (portfolio,) = rows(db, Portfolio)
    assert portfolio.mode == "backtest" and portfolio.backtest_run_id == run_id
    sigs = rows(db, Signal)
    assert all(s.mode == "backtest" and s.backtest_run_id == run_id for s in sigs)
    assert min(s.generated_at for s in sigs) >= START
    buy = rows(db, Trade, Trade.seq)[0]
    assert buy.side == "BUY" and buy.executed_at > sigs[0].generated_at  # filled after the decision

    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    def override():
        with db() as s:
            yield s

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    assert api.get("/api/v1/trades").json() == [] and api.get("/api/v1/signals").json() == []
    assert api.get("/api/v1/portfolio").status_code == 404  # no live portfolio was created
    detail = api.get(f"/api/v1/backtests/{run_id}").json()
    assert detail["summary"]["trade_count"] >= 1 and len(detail["snapshots"]) == 21
    assert len(api.get(f"/api/v1/backtests/{run_id}/trades").json()) >= 1
    assert api.get("/api/v1/backtests").json()[0]["id"] == str(run_id)


def test_a_bar_that_arrives_late_is_not_seen_early(db):
    choppy(db, poison=True)
    news(db, datetime(2026, 8, 25, 12, tzinfo=UTC), GOOD, 1)
    backtest(db)
    trades = rows(db, Trade, Trade.seq)
    sells = [t for t in trades if t.side == "SELL"]
    assert trades[0].side == "BUY" and len(sells) == 1
    assert sells[0].reason == "stop_loss" and sells[0].executed_at == LATE_BAD
    snaps = [x for x in rows(db, PortfolioSnapshot, PortfolioSnapshot.as_of) if x.as_of < LATE_BAD]
    assert all(x.positions_value for x in snaps if x.as_of > datetime(2026, 8, 27, tzinfo=UTC))
    positions = rows(db, Position)
    assert positions[0].closed_at == LATE_BAD  # held until the correction was published


def test_news_collected_after_the_step_is_invisible(db):
    choppy(db)
    news(db, datetime(2026, 8, 25, 12, tzinfo=UTC), GOOD, 1)
    # Bad news dated Aug 24 that was only collected on Sep 20, long after the window closes.
    news(db, datetime(2026, 8, 24, 12, tzinfo=UTC),
         "Apple misses estimates, cuts guidance and shares plunge", 2,
         collected=datetime(2026, 9, 20, tzinfo=UTC))  # fmt: skip
    backtest(db)
    for s in rows(db, Signal):
        assert s.action in ("BUY", "STRONG_BUY", "HOLD")  # never the SELL/AVOID it would cause
        assert all("misses" not in e["quote_or_fact"] for e in s.evidence)


def test_two_runs_give_the_same_result(db):
    choppy(db, poison=True)
    news(db, datetime(2026, 8, 25, 12, tzinfo=UTC), GOOD, 1)
    backtest(db)
    backtest(db)
    first, second = rows(db, BacktestRun, BacktestRun.started_at)
    a, b = first.summary, second.summary
    assert a["portfolio"] == b["portfolio"] and a["trade_count"] == b["trade_count"]
    by_run = {}
    with db() as s:
        for t, pf in s.execute(
            select(Trade, Portfolio)
            .join(Portfolio, Portfolio.id == Trade.portfolio_id)
            .order_by(Trade.seq)
        ):
            by_run.setdefault(pf.backtest_run_id, []).append(trade_key(t))
    assert by_run[first.id] == by_run[second.id] and by_run[first.id]
