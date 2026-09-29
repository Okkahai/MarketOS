from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.market.ingest import fetch_window

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def test_first_run_backfills_configured_history():
    s = Settings(market_history_days=400, market_intraday_backfill_hours=24)
    assert fetch_window(None, "1d", NOW, s) == (NOW - timedelta(days=400), NOW)
    assert fetch_window(None, "1m", NOW, s) == (NOW - timedelta(hours=24), NOW)


def test_later_runs_refetch_a_short_overlap_to_catch_corrections():
    s = Settings(market_overlap_days=5)
    latest = datetime(2026, 9, 28, tzinfo=UTC)
    assert fetch_window(latest, "1d", NOW, s) == (latest - timedelta(days=5), NOW)
    assert fetch_window(latest, "1m", NOW, s) == (latest - timedelta(minutes=30), NOW)
