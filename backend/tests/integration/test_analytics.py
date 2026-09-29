"""Signal evaluation and the analytics API against a real PostgreSQL."""

# ruff: noqa: F811  (the db fixture is shared from test_trading)

from datetime import timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.analytics.evaluate import run_evaluate_signals
from app.core.clock import FixedClock
from app.models import (
    PerformanceEvaluation,  # noqa: E402
    Portfolio,
    PortfolioSnapshot,
)
from tests.integration.test_trading import (  # noqa: F401  (db is a fixture)
    FRI,
    MON,
    T0,
    bar,
    cycle,
    db,
    make_signal,
    put_bars,
    pytestmark,
    rows,
)


def evaluate(db, at):
    run_evaluate_signals(db, clock=FixedClock(at))


def market(db):
    put_bars(db, "AAPL", bar(FRI, "100", "100", "100", "100"), bar(MON, "100", "103", "99", "102"),
             bar(MON + timedelta(days=1), "102", "110", "101", "108"))  # fmt: skip
    put_bars(db, "SPY", bar(FRI, "400", "400", "400", "400"), bar(MON, "400", "405", "399", "404"),
             bar(MON + timedelta(days=1), "404", "410", "403", "408"))  # fmt: skip


def test_a_finished_horizon_is_judged_against_what_the_model_saw_and_the_benchmark(db):
    market(db)
    make_signal(db, action="BUY")
    make_signal(db, action="SELL")
    make_signal(db, action="HOLD")
    evaluate(db, T0 + timedelta(days=2))  # 1-day horizon is over; 3 days is not
    evs = rows(db, PerformanceEvaluation, PerformanceEvaluation.created_at)
    assert {e.horizon for e in evs} == {"1d"} and len(evs) == 3
    buy = next(e for e in evs if e.direction_correct is True)
    assert (buy.start_price, buy.end_price) == (D(100), D(102))  # last close seen -> Monday close
    assert (buy.return_pct, buy.mfe_pct, buy.mae_pct) == (D("2"), D("3"), D("-1"))
    assert (buy.benchmark_symbol, buy.benchmark_return_pct, buy.excess_return_pct) == (
        "SPY", D("1"), D("1"))  # fmt: skip
    assert sorted(str(e.direction_correct) for e in evs) == [
        "False",
        "None",
        "True",
    ]  # SELL was wrong

    evaluate(db, T0 + timedelta(days=2, hours=1))
    assert len(rows(db, PerformanceEvaluation)) == 3  # written once


def test_no_evaluation_without_enough_bars_and_rows_are_immutable(db):
    put_bars(db, "AAPL", bar(FRI, "100", "100", "100", "100"))
    make_signal(db)
    evaluate(db, T0 + timedelta(days=10))
    assert rows(db, PerformanceEvaluation) == []  # nothing to judge with: no guess
    market(db)
    evaluate(db, T0 + timedelta(days=2))
    with db() as s:
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE performance_evaluations SET return_pct = 99"))


def test_summary_and_evaluations_api(db):
    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    def override():
        with db() as s:
            yield s

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    empty = api.get("/api/v1/analytics/summary").json()
    assert empty["portfolio"]["return_pct"] is None and empty["trades"]["closed"] == 0

    market(db)
    make_signal(db, action="BUY")
    make_signal(db, action="SELL")
    cycle(db, T0)  # creates the portfolio
    evaluate(db, T0 + timedelta(days=2))
    with db() as s:
        p = s.scalar(select(Portfolio))
        for i, total in enumerate((10000, 10200, 10100)):
            at = T0 + timedelta(days=i, hours=1)
            snap = PortfolioSnapshot(
                portfolio_id=p.id,
                as_of=at,
                cash=D(total),
                total_value=D(total),
                complete=True,
                details={},
            )
            s.add(snap)  # fmt: skip
        s.add(
            PortfolioSnapshot(
                portfolio_id=p.id,
                as_of=T0 + timedelta(days=3),
                cash=D(0),
                total_value=None,
                complete=False,
                details={},
            )
        )
        s.commit()
    body = api.get("/api/v1/analytics/summary").json()
    port = body["portfolio"]
    assert port["days"] == 3 and port["incomplete_snapshots"] == 1
    assert port["return_pct"] == pytest.approx(1.0)
    assert port["max_drawdown_pct"] == pytest.approx(100 / 10200 * 100)
    assert {b["symbol"] for b in body["benchmarks"]} == {"SPY", "BTC-USD", "CASH"}
    h1 = next(x for x in body["predictions"] if x["horizon"] == "1d")
    assert (h1["evaluated"], h1["hit_rate"]) == (2, 0.5)  # one right, one wrong, both counted
    wrong = api.get("/api/v1/analytics/evaluations?wrong_only=true").json()
    assert [w["action"] for w in wrong] == ["SELL"]
