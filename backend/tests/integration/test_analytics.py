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


def test_old_signals_cannot_starve_newer_ones(db, monkeypatch):
    """Pages of one: every run walks all signals with a due, missing horizon (F2)."""
    monkeypatch.setattr("app.analytics.evaluate.PER_RUN", 1)
    market(db)
    sigs = [make_signal(db, at=T0 + timedelta(minutes=i)) for i in range(3)]
    evaluate(db, T0 + timedelta(days=2))
    evs = rows(db, PerformanceEvaluation)
    assert sorted(e.signal_id for e in evs) == sorted(s.id for s in sigs)
    assert {e.horizon for e in evs} == {"1d"}
    newest = make_signal(db, at=T0 + timedelta(minutes=10))
    evaluate(db, T0 + timedelta(days=2))  # the three older ones still miss 3d, 7d, 30d
    assert newest.id in {e.signal_id for e in rows(db, PerformanceEvaluation)}


def test_prediction_averages_are_signed_by_the_call_and_skip_self_benchmarks(db):
    """A BUY that rose 2% and an AVOID that fell 2% both earned 2% (F8)."""
    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    def override():
        with db() as s:
            yield s

    app.dependency_overrides[get_db] = override
    market(db)  # AAPL +2%, SPY +1% on Monday
    put_bars(db, "MSFT", bar(FRI, "100", "100", "100", "100"), bar(MON, "100", "100", "97", "98"))
    make_signal(db, "AAPL", action="BUY")
    make_signal(db, "MSFT", action="AVOID")
    make_signal(db, "SPY", action="BUY", reference_price=D("400"))  # SPY vs SPY: excess 0
    make_signal(db, "AAPL", action="HOLD")
    evaluate(db, T0 + timedelta(days=2))
    h1 = next(x for x in TestClient(app).get("/api/v1/analytics/summary").json()["predictions"]
              if x["horizon"] == "1d")  # fmt: skip
    assert h1["evaluated"] == 4 and h1["hit_rate"] == 1.0
    assert h1["avg_signed_return_pct"] == pytest.approx((2 + 2 + 1) / 3)
    assert h1["excess_judged"] == 2  # AAPL +1 and MSFT -3 signed +3; SPY is left out
    assert h1["avg_signed_excess_pct"] == pytest.approx(2.0)
    avoid = next(a for a in h1["by_action"] if a["action"] == "AVOID")
    assert (avoid["evaluated"], avoid["avg_signed_return_pct"]) == (1, pytest.approx(2.0))
