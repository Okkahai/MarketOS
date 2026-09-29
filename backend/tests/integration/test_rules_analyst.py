"""The free analyst through the whole pipeline: context, journal, cost, risk and a paper trade."""

# ruff: noqa: F811, F401  (the db fixture and pytestmark are shared from test_ai)
from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

from app.ai.analyze import run_ai_analysis
from app.ai.rules_llm import RulesClient
from app.core.clock import FixedClock
from app.core.config import Settings
from app.market.bars import Bar, stock_daily_available_at
from app.market.repository import store_bars
from app.models import AiAnalysis, Asset, Signal
from tests.integration.test_ai import DAY0, NOW, add_news, db, pytestmark


def choppy_bars(db, n=30):
    """Closes zig-zag around 100, so RSI is near 50 and no guard fires."""
    with db() as s:
        asset = s.scalar(select(Asset).where(Asset.symbol == "AAPL"))
        bars = []
        for i in range(n):
            ts = DAY0 + timedelta(days=i)
            c = D(100 + (i % 2) * 2)
            bars.append(Bar(ts=ts, open=c, high=c + 1, low=c - 1, close=c, volume=D(1000),
                            available_at=stock_daily_available_at(ts.date())))  # fmt: skip
        store_bars(s, asset_id=asset.id, interval="1d", provider="tiingo", bars=bars, run_id=None,
                   now=DAY0 + timedelta(days=n + 5))  # fmt: skip


def run(db, at=NOW):
    return run_ai_analysis(db, Settings(), RulesClient(), clock=FixedClock(at))


def signals(db):
    with db() as s:
        return list(s.scalars(select(Signal)))


def test_defaults_use_the_free_analyst_and_need_no_key_or_price():
    s = Settings()
    assert s.ai_provider == "rules" and s.anthropic_api_key is None
    assert s.ai_analysis_model == "rules-analysis-1"
    assert s.ai_model_prices["rules-analysis-1"]["output"] == 0


def test_good_news_becomes_a_valid_buy_signal_at_zero_cost(db):
    choppy_bars(db)
    add_news(db, title="Apple beats estimates and raises guidance, shares surges on strong demand")
    run(db)
    (sig,) = signals(db)
    assert sig.action in ("BUY", "STRONG_BUY") and sig.suggested_stop_loss_pct > 0
    assert sig.thesis and sig.bear_case and sig.evidence
    with db() as s:
        calls = list(s.scalars(select(AiAnalysis)))
    assert {c.stage for c in calls} == {"triage", "analysis"}
    assert all(c.validation_status == "valid" and c.estimated_cost_usd == 0 for c in calls)
    run(db, NOW + timedelta(minutes=5))
    assert len(signals(db)) == 1  # not analysed twice


def test_neutral_news_makes_no_signal(db):
    choppy_bars(db)
    add_news(db, title="Apple to hold its annual shareholder meeting next month")
    run(db)
    assert signals(db) == []


def test_bad_news_on_an_unheld_stock_is_avoid_and_never_trades(db):
    choppy_bars(db)
    add_news(db, title="Apple misses estimates, cuts guidance and shares plunge")
    run(db)
    (sig,) = signals(db)
    assert sig.action == "AVOID"
