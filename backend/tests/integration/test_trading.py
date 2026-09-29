"""Paper trading against a real PostgreSQL: decisions, fills, exits, ledger and reconciliation."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.clock import FixedClock
from app.core.config import Settings
from app.market.bars import Bar, stock_daily_available_at
from app.market.repository import store_bars
from app.market.seed import seed_assets
from app.models import (
    AiAnalysis,
    Asset,
    CashLedger,
    ContextSnapshot,
    Event,
    Order,
    Portfolio,
    Position,
    RiskDecision,
    Signal,
    SystemRun,
    Trade,
)
from app.trading.engine import run_paper_cycle
from app.trading.reconcile import reconcile, run_reconcile

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]

FRI = datetime(2026, 7, 31, tzinfo=UTC)
MON = datetime(2026, 8, 3, tzinfo=UTC)
T0 = datetime(2026, 8, 3, 21, 0, tzinfo=UTC)  # Monday evening, after the close
SETTINGS = Settings()


@pytest.fixture
def db(migrated):
    factory = sessionmaker(bind=migrated, expire_on_commit=False)
    with factory() as s:
        seed_assets(s)
    return factory


def bar(day: datetime, o, h, low, c) -> Bar:
    return Bar(ts=day, open=D(o), high=D(h), low=D(low), close=D(c), volume=D(1000),
               available_at=stock_daily_available_at(day.date()))  # fmt: skip


def put_bars(db, symbol, *bars: Bar):
    with db() as s:
        asset = s.scalar(select(Asset).where(Asset.symbol == symbol))
        store_bars(s, asset_id=asset.id, interval="1d", provider="tiingo", bars=list(bars),
                   run_id=None, now=datetime(2026, 9, 1, tzinfo=UTC))  # fmt: skip


def flat_bars(db, symbol, price="100"):
    put_bars(db, symbol, bar(FRI, price, price, price, price))


def make_signal(db, symbol="AAPL", action="BUY", conf="0.700", at=T0, **kw) -> Signal:
    with db() as s:
        asset = s.scalar(select(Asset).where(Asset.symbol == symbol))
        event = Event(title="test", category="earnings", importance=D("0.5"), confidence=D("0.5"),
                      horizon="days", first_seen_at=at, last_updated_at=at, available_at=at,
                      method_version="t", score_details={})  # fmt: skip
        snap = ContextSnapshot(as_of=at, payload={}, payload_sha256="x", builder_version="t")
        s.add_all([event, snap])
        s.flush()
        analysis = AiAnalysis(context_snapshot_id=snap.id, event_id=event.id, stage="analysis",
                              as_of=at, model="m", prompt_version="t", request_hash="h",
                              validation_status="valid")  # fmt: skip
        s.add(analysis)
        s.flush()
        sig = Signal(analysis_id=analysis.id, asset_id=asset.id, generated_at=at, action=action,
                     confidence=D(conf), time_horizon="7d",
                     reference_price=D("100"), key_catalysts=[], risks=[],
                     invalidation_conditions=[], evidence=[], thesis="t", bear_case="b",
                     **{"direction": "long", "reference_price_ts": FRI, **kw})  # fmt: skip
        s.add(sig)
        s.commit()
        return sig


def cycle(db, at, **kw):
    run_paper_cycle(db, Settings(**kw), clock=FixedClock(at))


def rows(db, model, *order):
    with db() as s:
        return list(s.scalars(select(model).order_by(*order)))


def check_books(db):
    with db() as s:
        for p in s.scalars(select(Portfolio)):
            assert reconcile(s, p) == []


def bought(db, **kw):
    """AAPL bought on Tuesday's open (100): 400 notional, 3.998 shares at 100.05."""
    flat_bars(db, "AAPL")
    make_signal(db, **kw)
    cycle(db, T0)
    tue = MON + timedelta(days=1)
    put_bars(db, "AAPL", bar(FRI, "100", "100", "100", "100"), bar(tue, "100", "101", "90", "100"))
    cycle(db, T0 + timedelta(days=1, hours=4))  # Wednesday 01:00 UTC: Tuesday's bar is usable


# --- the buy path ---------------------------------------------------------------------------


def test_signal_becomes_decision_order_and_a_fill_at_the_next_open(db):
    flat_bars(db, "AAPL")
    sig = make_signal(db)
    cycle(db, T0)
    (decision,) = rows(db, RiskDecision)
    assert decision.signal_id == sig.id and decision.decision == "approved"
    assert decision.approved_notional == D(400) and decision.engine_version == "risk-1"
    assert decision.rules_evaluated and decision.config["max_position_pct"] == "10"
    (order,) = rows(db, Order)
    assert order.status == "pending" and order.side == "BUY" and order.signal_time == T0
    assert rows(db, Trade) == []  # no bar after the decision yet: nothing is filled at a guess

    tue = MON + timedelta(days=1)
    put_bars(db, "AAPL", bar(FRI, "100", "100", "100", "100"), bar(tue, "100", "101", "90", "100"))
    cycle(db, T0 + timedelta(hours=1))  # Tuesday's bar is not available until Wednesday 00:00Z
    assert rows(db, Trade) == []
    cycle(db, T0 + timedelta(days=1, hours=4))

    (trade,) = rows(db, Trade)
    assert trade.side == "BUY" and trade.signal_id == sig.id
    assert trade.executed_at == datetime(2026, 8, 4, 13, 30, tzinfo=UTC)  # Tuesday's open
    assert (trade.reference_price, trade.price) == (D(100), D("100.05"))  # 5 bps against us
    assert trade.quantity == D("3.998") and trade.fee == 0
    assert trade.cash_change == D("-399.9999")
    (pos,) = rows(db, Position)
    assert (pos.quantity, pos.avg_cost, pos.signal_id) == (D("3.998"), D("100.05"), sig.id)
    assert pos.stop_price == D("92.046")  # default 8% stop under the average cost
    (portfolio,) = rows(db, Portfolio)
    assert portfolio.cash == D("9600.0001")
    assert [(r.kind, r.amount) for r in rows(db, CashLedger, CashLedger.seq)] == [
        ("deposit", D(10000)), ("trade", D("-399.9999"))]  # fmt: skip
    assert rows(db, Order)[0].status == "filled"
    check_books(db)


def test_rejected_signals_are_kept_with_their_reasons_and_place_no_order(db):
    flat_bars(db, "AAPL")
    make_signal(db, conf="0.500")
    make_signal(db, action="HOLD", conf="0.900")
    cycle(db, T0)
    decisions = rows(db, RiskDecision)
    assert [d.decision for d in decisions] == ["rejected", "rejected"]
    assert any("min_confidence" in r for r in decisions[0].reasons)
    assert rows(db, Order) == [] and len(rows(db, Signal)) == 2
    cycle(db, T0 + timedelta(minutes=5))
    assert len(rows(db, RiskDecision)) == 2  # decided once


def test_pending_order_expires_when_no_price_ever_arrives(db):
    flat_bars(db, "AAPL")
    make_signal(db)
    cycle(db, T0)
    cycle(db, T0 + timedelta(hours=73))
    assert rows(db, Order)[0].status == "expired" and rows(db, Trade) == []
    assert rows(db, Portfolio)[0].cash == D(10000)


def test_pending_buys_reserve_cash_and_sector_room(db):
    """Three tech buys at the 10% cap: the 30% sector cap must hold before any of them fills."""
    for sym in ("AAPL", "MSFT", "NVDA", "AMD"):
        flat_bars(db, sym)
        make_signal(db, sym, suggested_position_size_pct=D("10"))
    cycle(db, T0)
    orders = rows(db, Order, Order.created_at)
    assert [o.notional for o in orders] == [D(1000), D(1000), D(1000)]
    last = rows(db, RiskDecision)[-1]
    assert last.decision == "rejected" and any("min_trade_size" in r for r in last.reasons)


def test_crypto_fills_on_the_first_minute_bar_after_the_decision_with_fees(db):
    def minute(ts, open_):
        return Bar(ts=ts, open=D(open_), high=D(open_), low=D(open_), close=D(open_),
                   volume=D(1), available_at=ts + timedelta(seconds=65))  # fmt: skip

    with db() as s:
        asset = s.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))
        first, second = minute(T0, "49000"), minute(T0 + timedelta(minutes=1), "50000")
        store_bars(s, asset_id=asset.id, interval="1m", provider="coinbase", run_id=None,
                   now=T0 + timedelta(hours=1), bars=[first, second])  # fmt: skip
    make_signal(db, "BTC-USD", reference_price_ts=T0 - timedelta(minutes=1))
    cycle(db, T0)
    assert rows(db, Trade) == []  # the bar opening at T0 is not "after" the decision at T0
    cycle(db, T0 + timedelta(minutes=5))
    (trade,) = rows(db, Trade)
    assert trade.executed_at == T0 + timedelta(minutes=1)
    assert (trade.reference_price, trade.price, trade.slippage_bps) == (D(50000), D(50050), D(10))
    assert abs(trade.fee - trade.quantity * trade.price * D("0.004")) < D("0.000001")
    spent = -trade.cash_change
    assert spent <= D(400) and D(400) - spent < D("0.001") * D(50050) / D(50000) * 2
    check_books(db)


# --- exits ----------------------------------------------------------------------------------


def test_stop_loss_gap_fills_at_the_open_and_ignores_the_entry_bar(db):
    bought(db)  # Tuesday's own low (90) is below the stop (92.046) but before/at the entry
    assert rows(db, Position)[0].closed_at is None
    wed = MON + timedelta(days=2)
    put_bars(db, "AAPL", bar(wed, "85", "86", "80", "82"))
    cycle(db, T0 + timedelta(days=2, hours=4))  # Thursday 01:00Z
    sell = rows(db, Trade, Trade.seq)[-1]
    assert (sell.side, sell.reason) == ("SELL", "stop_loss")
    assert sell.reference_price == D(85) and sell.price == D("84.9575")  # gap: open, then 5 bps
    assert sell.executed_at == stock_daily_available_at(wed.date())
    assert sell.realized_pnl == D("3.998") * D("84.9575") - D("3.998") * D("100.05")
    (pos,) = rows(db, Position)
    assert pos.closed_at is not None and pos.quantity == 0
    check_books(db)


def test_take_profit_fills_at_the_target_and_stop_wins_a_double_hit(db):
    bought(db, suggested_take_profit_pct=D(10))
    assert rows(db, Position)[0].target_price == D("110.055")
    wed = MON + timedelta(days=2)
    put_bars(db, "AAPL", bar(wed, "101", "120", "99", "118"))
    cycle(db, T0 + timedelta(days=2, hours=4))
    sell = rows(db, Trade, Trade.seq)[-1]
    assert (sell.reason, sell.reference_price) == ("take_profit", D("110.055"))
    check_books(db)


def test_stop_beats_target_when_one_bar_touches_both(db):
    bought(db, suggested_take_profit_pct=D(10))
    wed = MON + timedelta(days=2)
    put_bars(db, "AAPL", bar(wed, "101", "120", "90", "100"))
    cycle(db, T0 + timedelta(days=2, hours=4))
    sell = rows(db, Trade, Trade.seq)[-1]
    assert (sell.reason, sell.reference_price) == ("stop_loss", D("92.046"))


def test_sell_signal_closes_the_position_at_the_next_open(db):
    bought(db)
    wed = MON + timedelta(days=2)
    put_bars(db, "AAPL", bar(wed, "104", "106", "103", "105"))
    at = T0 + timedelta(days=1, hours=5)  # Wednesday 02:00Z, after Tuesday's bar exists
    make_signal(db, action="SELL", conf="0.300", at=at, direction="exit")
    cycle(db, at)
    assert len(rows(db, Trade)) == 1  # Wednesday's open comes later than the decision...
    cycle(db, T0 + timedelta(days=2, hours=4))
    sell = rows(db, Trade, Trade.seq)[-1]
    assert (sell.reason, sell.executed_at) == ("signal", datetime(2026, 8, 5, 13, 30, tzinfo=UTC))
    assert rows(db, Position)[0].closed_at is not None
    assert rows(db, Portfolio)[0].cash > D(10000)
    check_books(db)


def test_drawdown_breaker_blocks_new_entries(db):
    bought(db)
    with db() as s:  # a value history whose peak is far above today's equity
        from app.models import PortfolioSnapshot

        p = s.scalar(select(Portfolio))
        peak = PortfolioSnapshot(
            portfolio_id=p.id,
            as_of=T0 + timedelta(days=1, hours=1),
            cash=D(0),
            total_value=D(20000),
            complete=True,
            details={},
        )
        s.add(peak)  # fmt: skip
        s.commit()
    flat_bars(db, "MSFT")
    at = T0 + timedelta(days=1, hours=6)
    make_signal(db, "MSFT", at=at)
    cycle(db, at)
    last = rows(db, RiskDecision, RiskDecision.decided_at)[-1]
    assert last.decision == "rejected" and any("drawdown_breaker" in r for r in last.reasons)


# --- ledger integrity -----------------------------------------------------------------------


def test_trades_ledger_decisions_and_snapshots_cannot_be_changed(db):
    bought(db)
    with db() as s:
        p = s.scalar(select(Portfolio))
        for table in ("trades", "cash_ledger", "risk_decisions"):
            for sql in (f"UPDATE {table} SET created_at = now()", f"DELETE FROM {table}"):  # noqa: S608
                with pytest.raises(DBAPIError):
                    s.execute(text(sql))
                s.rollback()
        p.cash = D(-1)
        with pytest.raises(IntegrityError):
            s.commit()  # cash can never go negative, even if the engine were wrong
    cycle(db, T0 + timedelta(days=1, hours=8))
    with db() as s:
        with pytest.raises(DBAPIError):
            s.execute(text("DELETE FROM portfolio_snapshots"))


def test_reconcile_reports_tampering_and_the_job_fails_loudly(db):
    bought(db)
    check_books(db)
    with db() as s:  # go around the app: turn the trigger off, edit history, turn it back on
        s.execute(text("ALTER TABLE cash_ledger DISABLE TRIGGER cash_ledger_append_only"))
        s.execute(text("UPDATE cash_ledger SET amount = amount + 5 WHERE kind = 'trade'"))
        s.execute(text("ALTER TABLE cash_ledger ENABLE TRIGGER cash_ledger_append_only"))
        s.execute(text("UPDATE positions SET quantity = quantity + 1"))
        s.commit()
        issues = reconcile(s, s.scalar(select(Portfolio)))
    text_ = " | ".join(issues)
    assert "ledger" in text_ and "positions hold" in text_
    run_id = run_reconcile(db, clock=FixedClock(T0))
    with db() as s:
        run = s.get(SystemRun, run_id)
        assert run.status == "failed" and run.details["issues"]["main"]


# --- API ------------------------------------------------------------------------------------


def test_api_portfolio_trades_decisions_orders_snapshots(db):
    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    def override():
        with db() as s:
            yield s

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    assert api.get("/api/v1/portfolio").status_code == 404
    bought(db)
    p = api.get("/api/v1/portfolio").json()
    assert p["cash"] == "9600.00010000" and p["starting_capital"] == "10000.00000000"
    (pos,) = p["positions"]
    assert pos["symbol"] == "AAPL" and pos["stop_price"] == "92.04600000"
    (trade,) = api.get("/api/v1/trades").json()
    assert trade["symbol"] == "AAPL" and trade["side"] == "BUY"
    (decision,) = api.get("/api/v1/risk-decisions?decision=approved").json()
    assert decision["signal_id"] == trade["signal_id"] and decision["rules_evaluated"]
    assert api.get("/api/v1/orders?status=filled").json()[0]["symbol"] == "AAPL"
    assert len(api.get("/api/v1/portfolio/snapshots").json()) >= 1


def test_the_analyst_sees_the_portfolio_once_it_exists(db):
    from app.trading.state import portfolio_view

    now = T0 + timedelta(days=1, hours=4)
    with db() as s:
        assert portfolio_view(s, SETTINGS, now) is None  # nothing invented before it exists
    bought(db)
    with db() as s:
        view = portfolio_view(s, SETTINGS, now)
    assert view["open_positions"] == 1 and view["cash"] == "9600.00010000"
    assert view["positions"][0]["symbol"] == "AAPL" and view["equity"] is not None
