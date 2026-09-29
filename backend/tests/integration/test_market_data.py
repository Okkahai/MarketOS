"""Market data storage, ingestion runs, indicators and API against a real PostgreSQL."""

import math
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
from app.market.bars import Bar, FetchResult, RejectedRow, stock_daily_available_at
from app.market.compute import run_compute_indicators
from app.market.ingest import run_ingest
from app.market.repository import get_bars, store_bars
from app.market.seed import UNIVERSE, seed_assets
from app.models import Asset, IndicatorValue, MarketPrice, ProviderFailure, SystemRun
from app.providers.base import ProviderAuthError, ProviderNotFound

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]

# All prices below are synthetic test values.
DAY0 = datetime(2026, 9, 21, tzinfo=UTC)


def daily_bar(day: int, close: str = "100", **kw) -> Bar:
    ts = DAY0 + timedelta(days=day)
    c = D(close)
    fields = dict(ts=ts, open=c, high=c + 1, low=c - 1, close=c, volume=D("1000"),
                  available_at=stock_daily_available_at(ts.date()))  # fmt: skip
    return Bar(**{**fields, **kw})


@pytest.fixture
def db(migrated):
    factory = sessionmaker(bind=migrated, expire_on_commit=False)
    with factory() as session:
        seed_assets(session)
    return factory


def asset(factory, symbol: str) -> Asset:
    with factory() as s:
        return s.scalars(select(Asset).where(Asset.symbol == symbol)).one()


def bars_of(factory, symbol: str, interval="1d", provider="tiingo") -> list[MarketPrice]:
    a = asset(factory, symbol)
    with factory() as s:
        return list(
            s.scalars(
                select(MarketPrice)
                .where(
                    MarketPrice.asset_id == a.id,
                    MarketPrice.interval == interval,
                    MarketPrice.provider == provider,
                )
                .order_by(MarketPrice.ts, MarketPrice.revision)
            )
        )


# --- seed -----------------------------------------------------------------------------------


def test_seed_creates_the_mvp_universe_once(migrated):
    factory = sessionmaker(bind=migrated)
    with factory() as s:
        assert seed_assets(s) == len(UNIVERSE) == 14
        assert seed_assets(s) == 0
        rows = s.scalars(select(Asset)).all()
    by_class = {c: sorted(a.symbol for a in rows if a.asset_class == c) for c in
                ("stock", "etf", "crypto")}  # fmt: skip
    assert by_class["stock"] == sorted("AAPL MSFT NVDA AMZN GOOGL META TSLA JPM AMD NFLX".split())
    assert by_class["etf"] == ["QQQ", "SPY"] and by_class["crypto"] == ["BTC-USD", "ETH-USD"]
    assert {a.symbol for a in rows if a.is_benchmark} == {"SPY", "QQQ", "BTC-USD"}


# --- storage rules -----------------------------------------------------------------------


def test_store_inserts_then_ignores_identical_bars(db):
    a = asset(db, "AAPL")
    now = DAY0 + timedelta(days=10)
    with db() as s:
        kw = dict(asset_id=a.id, interval="1d", provider="tiingo", run_id=None, now=now)
        first = store_bars(s, bars=[daily_bar(0), daily_bar(1)], **kw)
        again = store_bars(s, bars=[daily_bar(0), daily_bar(1)], **kw)
    assert (first.written, first.revisions, first.unchanged) == (2, 0, 0)
    assert (again.written, again.revisions, again.unchanged) == (0, 0, 2)
    assert len(bars_of(db, "AAPL")) == 2


def test_changed_bar_becomes_a_new_revision_known_only_from_now(db):
    a = asset(db, "AAPL")
    bar = daily_bar(0, "100")
    corrected = daily_bar(0, "100.5")
    t_first, t_fix = DAY0 + timedelta(days=2), DAY0 + timedelta(days=5)
    with db() as s:
        kw = dict(asset_id=a.id, interval="1d", provider="tiingo", run_id=None)
        store_bars(s, bars=[bar], now=t_first, **kw)
        stats = store_bars(s, bars=[corrected], now=t_fix, **kw)
        assert (stats.written, stats.revisions) == (0, 1)

        rows = bars_of(db, "AAPL")
        assert [(r.revision, r.close) for r in rows] == [(0, D("100")), (1, D("100.5"))]
        assert rows[1].available_at == t_fix  # the correction was not knowable earlier

        # Point in time: before the correction is published the old value is what was known.
        before = get_bars(s, a.id, "1d", "tiingo", t_fix - timedelta(seconds=1), 10)
        after = get_bars(s, a.id, "1d", "tiingo", t_fix, 10)
    assert [b.close for b in before] == [D("100")]
    assert [b.close for b in after] == [D("100.5")]


def test_bars_that_are_not_available_yet_are_skipped_not_stored(db):
    a = asset(db, "AAPL")
    bar = daily_bar(0)
    with db() as s:
        stats = store_bars(
            s, asset_id=a.id, interval="1d", provider="tiingo", bars=[bar], run_id=None,
            now=bar.available_at - timedelta(seconds=1),
        )  # fmt: skip
    assert stats.not_yet_available == 1 and stats.written == 0
    assert bars_of(db, "AAPL") == []


def test_get_bars_never_returns_the_future(db):
    a = asset(db, "AAPL")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=[daily_bar(i, str(100 + i)) for i in range(6)],
                   now=DAY0 + timedelta(days=30))  # fmt: skip
        as_of = daily_bar(2).available_at  # just after day 2's bar became available
        seen = get_bars(s, a.id, "1d", "tiingo", as_of, 100)
    assert [b.close for b in seen] == [D("100"), D("101"), D("102")]
    assert all(b.available_at <= as_of for b in seen)


def test_raw_bars_are_append_only(db):
    a = asset(db, "AAPL")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=[daily_bar(0)], now=DAY0 + timedelta(days=5))  # fmt: skip
    with db() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE market_prices SET close = 1"))
        s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM market_prices"))


def test_database_rejects_inconsistent_ohlc_even_if_python_checks_are_bypassed(db):
    a = asset(db, "AAPL")
    with db() as s, pytest.raises(IntegrityError):
        s.add(
            MarketPrice(
                asset_id=a.id, interval="1d", ts=DAY0, open=D("10"), high=D("9"), low=D("8"),
                close=D("9"), volume=D("1"), provider="tiingo", available_at=DAY0,
            )
        )  # fmt: skip
        s.commit()


# --- ingestion runs ---------------------------------------------------------------------


NOW = DAY0 + timedelta(days=20)


def ingest(db, fetcher, **kw):
    return run_ingest(
        db, Settings(), job_name="ingest_stock_daily", provider="tiingo", interval="1d",
        asset_classes=("stock", "etf"), fetcher=fetcher, clock=FixedClock(NOW),
        missing_credentials_hint="Set TIINGO_API_KEY.", **kw,
    )  # fmt: skip


def run_row(db, run_id) -> SystemRun:
    with db() as s:
        return s.get(SystemRun, run_id)


def test_ingest_run_records_counts_and_is_idempotent(db):
    def fetcher(a, start, end):
        return FetchResult(bars=[daily_bar(0), daily_bar(1)])

    first = run_row(db, ingest(db, fetcher))
    assert first.status == "succeeded" and first.provider == "tiingo"
    assert first.items_fetched == 24 and first.items_written == 24  # 12 stock/etf assets x 2
    assert first.details["assets"]["AAPL"]["written"] == 2

    second = run_row(db, ingest(db, fetcher))
    assert second.status == "succeeded" and second.items_written == 0
    assert second.details["assets"]["AAPL"]["unchanged"] == 2
    assert len(bars_of(db, "AAPL")) == 2
    assert all(r.run_id == first.id for r in bars_of(db, "AAPL"))


def test_one_failing_symbol_makes_the_run_partial_and_writes_nothing_for_it(db):
    def fetcher(a, start, end):
        if a.symbol == "AMD":
            raise ProviderNotFound("no data", http_status=404)
        return FetchResult(bars=[daily_bar(0)])

    row = run_row(db, ingest(db, fetcher))
    assert row.status == "partial"
    assert "ProviderNotFound" in row.details["assets"]["AMD"]["error"]
    assert bars_of(db, "AMD") == [] and len(bars_of(db, "AAPL")) == 1
    with db() as s:
        failure = s.scalars(select(ProviderFailure)).one()
    assert (failure.provider, failure.subject, failure.http_status, failure.run_id) == (
        "tiingo", "AMD", 404, row.id,
    )  # fmt: skip


def test_auth_failure_stops_the_run_and_marks_it_failed(db):
    calls = []

    def fetcher(a, start, end):
        calls.append(a.symbol)
        raise ProviderAuthError("bad key", http_status=401)

    row = run_row(db, ingest(db, fetcher))
    assert row.status == "failed" and len(calls) == 1  # did not hammer the provider
    assert "ProviderAuthError" in row.details["aborted"]
    with db() as s:
        assert s.scalars(select(MarketPrice)).all() == []


def test_missing_credentials_are_reported_as_a_skipped_run(db):
    row = run_row(db, ingest(db, None))
    assert row.status == "skipped"
    assert "TIINGO_API_KEY" in row.details["reason"]
    with db() as s:
        assert s.scalars(select(MarketPrice)).all() == []


def test_rejected_rows_are_recorded_and_flag_the_run(db):
    def fetcher(a, start, end):
        return FetchResult(bars=[daily_bar(0)], rejected=[RejectedRow("ValueError: bad", "{}")])

    row = run_row(db, ingest(db, fetcher))
    assert row.status == "partial"
    with db() as s:
        failures = s.scalars(select(ProviderFailure)).all()
    assert failures and failures[0].error_type == "RejectedBars"


# --- indicators -----------------------------------------------------------------------------


def series_bars(n: int, start_price: float = 100.0) -> list[Bar]:
    out = []
    for i in range(n):
        c = D(str(round(start_price + 10 * math.sin(i / 7) + i * 0.1, 4)))
        out.append(daily_bar(i, str(c)))
    return out


def test_indicator_job_only_uses_bars_available_at_the_clock_time(db):
    a, spy = asset(db, "AAPL"), asset(db, "SPY")
    with db() as s:
        for x in (a, spy):
            store_bars(s, asset_id=x.id, interval="1d", provider="tiingo", run_id=None,
                       bars=series_bars(260), now=DAY0 + timedelta(days=400))  # fmt: skip
    settings = Settings(indicator_store_bars=5)

    early_clock = FixedClock(stock_daily_available_at((DAY0 + timedelta(days=100)).date()))
    run_compute_indicators(db, settings, clock=early_clock)
    with db() as s:
        rows = s.scalars(select(IndicatorValue).where(IndicatorValue.asset_id == a.id)).all()
    names = {r.name for r in rows}
    assert {"rsi_14", "sma_50", "rel_strength_20", "corr_20"} <= names
    assert "sma_200" not in names  # only 101 bars existed at that time
    assert max(r.ts for r in rows) == DAY0 + timedelta(days=100)
    assert all(r.computed_from_available_at <= early_clock.now() for r in rows)

    late_clock = FixedClock(DAY0 + timedelta(days=401))
    run_compute_indicators(db, settings, clock=late_clock)
    with db() as s:
        latest = s.scalars(
            select(IndicatorValue).where(
                IndicatorValue.asset_id == a.id, IndicatorValue.name == "sma_200"
            )
        ).all()
    assert latest and max(r.ts for r in latest) == DAY0 + timedelta(days=259)


def test_indicator_job_is_repeatable(db):
    a = asset(db, "AAPL")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=series_bars(80), now=DAY0 + timedelta(days=400))  # fmt: skip
    clock = FixedClock(DAY0 + timedelta(days=401))
    run_compute_indicators(db, Settings(indicator_store_bars=3), clock=clock)
    with db() as s:
        first = s.scalar(text("SELECT count(*) FROM indicator_values"))
    run_compute_indicators(db, Settings(indicator_store_bars=3), clock=clock)
    with db() as s:
        assert s.scalar(text("SELECT count(*) FROM indicator_values")) == first > 0


# --- API ---------------------------------------------------------------------------------


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    from app.main import create_app

    return TestClient(create_app())


def recent_bar(days_ago: int, close: str, adj: str | None = None) -> Bar:
    ts = (datetime.now(UTC) - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0,
                                                                microsecond=0)  # fmt: skip
    c = D(close)
    return Bar(ts=ts, open=c, high=c + 1, low=c - 1, close=c, volume=D("5"),
               available_at=ts + timedelta(hours=1),
               adj_close=D(adj) if adj else None)  # fmt: skip


def test_watchlist_shows_missing_data_as_missing(client):
    rows = client.get("/api/v1/market/watchlist").json()
    assert len(rows) == 14
    assert all(r["last_close"] is None and r["change_pct"] is None for r in rows)


def test_watchlist_and_bars_return_exact_decimal_strings(client, db):
    a = asset(db, "AAPL")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=[recent_bar(3, "100"), recent_bar(2, "103.30")],
                   now=datetime.now(UTC))  # fmt: skip
    row = next(r for r in client.get("/api/v1/market/watchlist").json() if r["symbol"] == "AAPL")
    assert row["last_close"] == "103.3000000000"
    assert row["change_pct"] == "3.3000"
    bars = client.get("/api/v1/assets/aapl/bars", params={"interval": "1d"}).json()
    assert [b["close"] for b in bars] == ["100.0000000000", "103.3000000000"]
    assert client.get("/api/v1/assets/AAPL/intervals").json() == ["1d"]


def test_change_uses_adjusted_closes_so_a_split_is_not_a_crash(client, db):
    a = asset(db, "NVDA")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=[recent_bar(3, "1000", adj="100"), recent_bar(2, "101", adj="101")],
                   now=datetime.now(UTC))  # fmt: skip
    row = next(r for r in client.get("/api/v1/market/watchlist").json() if r["symbol"] == "NVDA")
    assert row["change_pct"] == "1.0000"


def test_bars_endpoint_honours_as_of(client, db):
    a = asset(db, "AAPL")
    b1, b2 = recent_bar(3, "100"), recent_bar(2, "101")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=[b1, b2], now=datetime.now(UTC))  # fmt: skip
    r = client.get("/api/v1/assets/AAPL/bars", params={"as_of": b1.available_at.isoformat()})
    assert len(r.json()) == 1
    assert client.get("/api/v1/assets/AAPL/bars", params={"as_of": "2026-01-01T00:00:00"}
                      ).status_code == 422  # naive timestamps are refused  # fmt: skip


def test_unknown_asset_and_bad_parameters(client):
    assert client.get("/api/v1/assets/NOPE/bars").status_code == 404
    assert client.get("/api/v1/assets/AAPL/bars", params={"interval": "7m"}).status_code == 422
    assert client.get("/api/v1/assets/AAPL/bars", params={"limit": 5000}).status_code == 422


def test_indicators_endpoint_returns_latest_values(client, db):
    a = asset(db, "AAPL")
    with db() as s:
        store_bars(s, asset_id=a.id, interval="1d", provider="tiingo", run_id=None,
                   bars=series_bars(60), now=DAY0 + timedelta(days=400))  # fmt: skip
    assert client.get("/api/v1/assets/AAPL/indicators").json() == []
    run_compute_indicators(db, Settings(), clock=FixedClock(DAY0 + timedelta(days=401)))
    rows = client.get("/api/v1/assets/AAPL/indicators").json()
    assert {"rsi_14", "sma_50"} <= {r["name"] for r in rows}
    assert len({r["ts"] for r in rows}) == 1  # one bar's worth: the newest


def test_assets_listing(client):
    body = client.get("/api/v1/assets").json()
    assert {a["symbol"] for a in body} >= {"AAPL", "BTC-USD", "SPY"}
