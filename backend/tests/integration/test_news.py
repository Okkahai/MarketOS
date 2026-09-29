"""News storage, dedup, ingest runs and API against a real PostgreSQL."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.clock import FixedClock
from app.core.config import Settings
from app.market.bars import RejectedRow
from app.market.seed import seed_assets
from app.models import NewsArticle, NewsSource, ProviderFailure, SystemRun
from app.news.ingest import run_news_source, tracked_symbols
from app.news.normalize import NewsFetch, RawArticle
from app.providers.base import ProviderAuthError, ProviderUnavailable

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
CLOCK = FixedClock(NOW)
SETTINGS = Settings()


@pytest.fixture
def db(migrated):
    factory = sessionmaker(bind=migrated, expire_on_commit=False)
    with factory() as session:
        seed_assets(session)
    return factory


def article(n: int, title: str | None = None, minutes_ago: int = 30, **kw) -> RawArticle:
    fields = dict(
        external_id=f"id{n}", url=f"https://news.test/{n}",
        title=title or f"Unique story {n} today",
        published_at=NOW - timedelta(minutes=minutes_ago), provider_tickers=("aapl",),
    )  # fmt: skip
    return RawArticle(**{**fields, **kw})


def ingest(db, fetch: NewsFetch | None, key="tiingo_news", clock=CLOCK):
    fetcher = None if fetch is None else (lambda since: fetch)
    run_id = run_news_source(db, SETTINGS, source_key=key, fetcher=fetcher, clock=clock)
    with db() as s:
        return s.get(SystemRun, run_id)


def articles(db) -> list[NewsArticle]:
    with db() as s:
        return list(s.scalars(select(NewsArticle).order_by(NewsArticle.published_at)))


def test_missing_credentials_is_a_skipped_run_with_no_articles(db):
    run = ingest(db, None)
    assert run.status == "skipped" and "not configured" in run.details["reason"]
    assert articles(db) == []


def test_articles_are_stored_with_point_in_time_timestamps(db):
    run = ingest(db, NewsFetch(articles=[article(1)]))
    assert run.status == "succeeded" and run.items_written == 1
    (a,) = articles(db)
    assert a.tickers == ["AAPL"] and a.published_at < a.collected_at == a.available_at == NOW
    assert a.sentiment is None and a.importance is None  # nothing guessed
    with db() as s:
        assert {r.key for r in s.scalars(select(NewsSource))} == {
            "tiingo_news", "sec_edgar", "fed_rss"}  # fmt: skip


def test_rerun_is_idempotent(db):
    fetch = NewsFetch(articles=[article(1), article(2)])
    ingest(db, fetch)
    run = ingest(db, fetch)
    assert run.details["already_stored"] == 2 and run.items_written == 0
    assert len(articles(db)) == 2


def test_duplicates_are_kept_and_point_at_the_first_copy(db):
    fetch = NewsFetch(articles=[
        article(1, "Apple shares jump after strong iPhone sales in China", 60),
        article(2, "Apple shares jump after strong iPhone sales in China", 50),
        article(3, "Apple shares jump after strong iPhone sales in China today", 40),
        article(4, "Something else entirely happened to Microsoft", 30),
    ])  # fmt: skip
    run = ingest(db, fetch)
    a1, a2, a3, a4 = articles(db)
    assert run.details["duplicates"] == 2
    assert a1.duplicate_of_id is None and a4.duplicate_of_id is None
    assert (a2.duplicate_of_id, a2.dedup_reason) == (a1.id, "same_title")
    assert (a3.duplicate_of_id, a3.dedup_reason) == (a1.id, "similar_title")


def test_duplicates_are_found_across_runs_and_sources(db):
    ingest(db, NewsFetch(articles=[article(1, "Fed holds rates steady as inflation cools", 90)]))
    later = article(7, "Fed holds rates steady as inflation cools", 20, url="https://fed.test/x")
    ingest(db, NewsFetch(articles=[later]), key="fed_rss")
    first, second = articles(db)
    assert second.duplicate_of_id == first.id


def test_filings_with_equal_titles_are_not_duplicates(db):
    same = "Apple Inc. (AAPL) filed 8-K: other events"
    fetch = NewsFetch(articles=[
        article(1, same, 60, url="https://sec.test/1", fixed_category="filing", text_dedup=False),
        article(2, same, 50, url="https://sec.test/2", fixed_category="filing", text_dedup=False),
    ])  # fmt: skip
    ingest(db, fetch, key="sec_edgar")
    assert [a.duplicate_of_id for a in articles(db)] == [None, None]


def test_rejected_items_and_errors_are_recorded_not_stored(db):
    fetch = NewsFetch(
        articles=[article(1), article(2, title=" "), article(3, url="javascript:alert(1)")],
        rejected=[RejectedRow("KeyError: 'publishedDate'", "{}")],
    )
    run = ingest(db, fetch)
    assert run.status == "partial" and run.details["rejected"] == 3 and run.items_written == 1
    with db() as s:
        (f,) = s.scalars(select(ProviderFailure)).all()
    assert f.error_type == "RejectedArticles" and "3 rows rejected" in f.error


def test_provider_error_marks_run_failed_and_stores_nothing(db):
    err = ProviderAuthError("401 from tiingo", http_status=401)
    err.endpoint = "/tiingo/news"
    run = ingest(db, NewsFetch(errors=[(None, err)]))
    assert run.status == "failed" and run.details["aborted"]
    assert articles(db) == []
    with db() as s:
        (f,) = s.scalars(select(ProviderFailure)).all()
    assert (f.provider, f.endpoint, f.http_status) == ("tiingo_news", "/tiingo/news", 401)


def test_partial_when_one_company_fails_and_others_arrive(db):
    fetch = NewsFetch(
        articles=[article(1)], errors=[("MSFT", ProviderUnavailable("boom", retry_count=3))]
    )
    run = ingest(db, fetch)
    assert run.status == "partial" and run.items_written == 1


def test_disabled_source_is_skipped(db):
    ingest(db, NewsFetch())
    with db() as s:
        s.execute(text("UPDATE news_sources SET is_enabled = false WHERE key = 'tiingo_news'"))
        s.commit()
    run = ingest(db, NewsFetch(articles=[article(1)]))
    assert run.status == "skipped" and articles(db) == []


def test_since_uses_latest_stored_article_with_overlap(db):
    seen = []
    ingest(db, NewsFetch(articles=[article(1, minutes_ago=600)]))
    run_news_source(
        db, SETTINGS, source_key="tiingo_news", fetcher=lambda s: seen.append(s) or NewsFetch(),
        clock=CLOCK,
    )  # fmt: skip
    assert seen == [NOW - timedelta(minutes=600) - timedelta(hours=2)]


def test_tracked_symbols_come_from_provider_symbols(db):
    with db() as s:
        assert "AAPL" in tracked_symbols(s, "tiingo", "stock")
        assert "SPY" not in tracked_symbols(s, "tiingo", "stock")
        assert "SPY" in tracked_symbols(s, "tiingo", "etf")


# --- database rules -----------------------------------------------------------------------


def test_database_rejects_bad_rows(db):
    ingest(db, NewsFetch(articles=[article(1)]))
    with db() as s:
        base = "UPDATE news_articles SET {} WHERE true"
        for sql in (
            "category = 'astrology'",
            "available_at = collected_at - interval '1 second'",
            "dedup_reason = 'same_url'",
        ):
            with pytest.raises((IntegrityError, DBAPIError)):
                s.execute(text(base.format(sql)))
            s.rollback()


def test_same_source_and_url_cannot_be_stored_twice(db):
    ingest(db, NewsFetch(articles=[article(1)]))
    ingest(db, NewsFetch(articles=[article(2, url="https://news.test/1?utm_source=x")]))
    assert len(articles(db)) == 1


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def client(db):
    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    def override():
        with db() as s:
            yield s

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_api_lists_filters_and_hides_duplicates_by_default(db, client):
    ingest(db, NewsFetch(articles=[
        article(1, "Apple shares jump after strong iPhone sales in China", 60),
        article(2, "Apple shares jump after strong iPhone sales in China", 50),
        article(3, "Fed holds interest rates steady", 40, provider_tickers=()),
    ]))  # fmt: skip
    rows = client.get("/api/v1/news/articles").json()
    assert [r["title"] for r in rows][0] == "Fed holds interest rates steady"
    assert len(rows) == 2
    assert len(client.get("/api/v1/news/articles?include_duplicates=true").json()) == 3
    only = client.get("/api/v1/news/articles?ticker=aapl").json()
    assert len(only) == 1 and only[0]["source"] == "tiingo_news"
    assert client.get("/api/v1/news/articles?category=central_bank").json()[0]["category"] == (
        "central_bank")  # fmt: skip
    assert client.get("/api/v1/news/articles?limit=0").status_code == 422


def test_api_as_of_hides_articles_not_yet_available(db, client):
    ingest(db, NewsFetch(articles=[article(1)]))
    before = (NOW - timedelta(hours=1)).isoformat()
    assert client.get("/api/v1/news/articles", params={"as_of": before}).json() == []
    assert len(client.get("/api/v1/news/articles", params={"as_of": NOW.isoformat()}).json()) == 1


def test_api_sources(db, client):
    ingest(db, NewsFetch())
    keys = [s["key"] for s in client.get("/api/v1/news/sources").json()]
    assert keys == ["fed_rss", "sec_edgar", "tiingo_news"]
