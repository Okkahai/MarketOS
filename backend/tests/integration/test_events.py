"""Event clustering job, point-in-time state and API against a real PostgreSQL."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.clock import FixedClock
from app.core.config import Settings
from app.events.build import run_cluster_events, state_as_of
from app.market.seed import seed_assets
from app.models import Asset, Event, EventAsset, EventSource, SystemRun
from app.news.ingest import run_news_source
from app.news.normalize import NewsFetch, RawArticle

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
SETTINGS = Settings()
APPLE_A = "Apple shares jump after strong iPhone sales in China"
APPLE_B = "Apple stock rises on strong iPhone demand in China"


@pytest.fixture
def db(migrated):
    factory = sessionmaker(bind=migrated, expire_on_commit=False)
    with factory() as session:
        seed_assets(session)
    return factory


def art(n, title, minutes_ago, tickers=("aapl",), outlet=None, **kw) -> RawArticle:
    kw.setdefault("url", f"https://news.test/{n}")
    kw.setdefault("published_at", NOW - timedelta(minutes=minutes_ago))
    return RawArticle(
        external_id=f"id{n}", title=title, provider_tickers=tickers,
        raw={"source": outlet} if outlet else {}, **kw,
    )  # fmt: skip


def news(db, *articles, key="tiingo_news", at=NOW):
    run_news_source(
        db, SETTINGS, source_key=key, fetcher=lambda since: NewsFetch(articles=list(articles)),
        clock=FixedClock(at),
    )  # fmt: skip


def cluster(db, at=NOW) -> SystemRun:
    run_id = run_cluster_events(db, SETTINGS, clock=FixedClock(at))
    with db() as s:
        return s.get(SystemRun, run_id)


def events(db) -> list[Event]:
    with db() as s:
        return list(s.scalars(select(Event).order_by(Event.first_seen_at)))


def test_no_articles_no_events(db):
    run = cluster(db)
    assert run.status == "succeeded" and run.details["new_events"] == 0 and events(db) == []


def test_related_articles_become_one_event_and_unrelated_a_second(db):
    news(db, art(1, APPLE_A, 120, outlet="reuters"), art(2, APPLE_B, 60, outlet="ap"),
         art(3, "Microsoft cloud outage hits Azure customers", 30, tickers=("msft",)))  # fmt: skip
    run = cluster(db)
    assert run.details["new_events"] == 2 and run.items_written == 3
    apple, msft = events(db)
    assert apple.title == APPLE_A and apple.method == "rule" and apple.status == "open"
    assert apple.score_details["articles"] == 2
    assert apple.score_details["publishers"] == ["ap", "reuters"]
    assert msft.title.startswith("Microsoft")
    with db() as s:
        links = s.execute(
            select(Asset.symbol, EventAsset.relevance, EventAsset.direction_hint)
            .join(EventAsset, EventAsset.asset_id == Asset.id)
            .where(EventAsset.event_id == apple.id)
        ).all()
    assert [(a, str(b), c) for a, b, c in links] == [("AAPL", "1.000", "unknown")]
    assert apple.sectors == ["Information Technology"]


def test_rerun_is_idempotent_and_later_articles_join_open_events(db):
    news(db, art(1, APPLE_A, 120))
    cluster(db)
    assert cluster(db).details["articles"] == 0
    news(db, art(2, APPLE_B, 30), at=NOW + timedelta(minutes=10))
    run = cluster(db, at=NOW + timedelta(minutes=10))
    assert run.details == {"articles": 1, "new_events": 0, "updated_events": 1, "closed": 0}
    (event,) = events(db)
    assert event.score_details["articles"] == 2
    assert event.available_at == NOW  # first article was usable at NOW
    assert event.last_updated_at == NOW + timedelta(minutes=10)


def test_copies_from_other_sources_join_the_original_event_as_corroboration(db):
    news(db, art(1, APPLE_A, 90, outlet="reuters"))
    news(db, art(2, APPLE_A, 60, outlet="ap", url="https://other.test/x"), key="fed_rss")
    cluster(db)
    (event,) = events(db)
    assert event.score_details["articles"] == 2
    assert event.score_details["publishers"] == ["ap", "reuters"]
    with db() as s:
        rows = s.scalars(select(EventSource)).all()
    assert len(rows) == 2


def test_every_article_belongs_to_exactly_one_event(db):
    news(
        db,
        *[art(i, f"Unrelated story number {i} about Apple {'x' * i}", 100 - i) for i in range(5)],
    )
    cluster(db)
    with db() as s:
        articles = s.scalar(text("SELECT count(*) FROM news_articles"))
        linked = s.scalar(text("SELECT count(DISTINCT article_id) FROM event_sources"))
    assert articles == linked == 5


def test_stale_events_close_and_a_new_story_starts_a_new_event(db):
    news(db, art(1, APPLE_A, 30))
    cluster(db)
    later = NOW + timedelta(hours=49)
    news(db, art(2, APPLE_B, 0, published_at=later - timedelta(minutes=10)), at=later)
    run = cluster(db, at=later)
    assert run.details["closed"] == 1 and run.details["new_events"] == 1
    first, second = events(db)
    assert first.status == "closed" and second.status == "open" and first.id != second.id


def test_filings_are_one_event_each(db):
    title = "Apple Inc. (AAPL) filed 8-K: other events"
    news(db, art(1, title, 90, url="https://sec.test/1", fixed_category="filing", text_dedup=False),
         art(2, title, 60, url="https://sec.test/2", fixed_category="filing", text_dedup=False),
         key="sec_edgar")  # fmt: skip
    assert cluster(db).details["new_events"] == 2


def test_state_as_of_ignores_articles_that_were_not_available_yet(db):
    news(db, art(1, APPLE_A, 120, outlet="reuters"))
    news(db, art(2, APPLE_B, 60, outlet="ap"), at=NOW + timedelta(hours=3))
    cluster(db, at=NOW + timedelta(hours=3))
    (event,) = events(db)
    with db() as s:
        early = state_as_of(s, event.id, NOW + timedelta(hours=1))
        late = state_as_of(s, event.id, NOW + timedelta(hours=4))
        before = state_as_of(s, event.id, NOW - timedelta(hours=1))
    assert early.details["articles"] == 1 and early.importance < late.importance
    assert late.details["articles"] == 2
    assert before is None


def test_database_rules(db):
    news(
        db, art(1, APPLE_A, 30), art(2, "Microsoft cloud outage hits Azure", 20, tickers=("msft",))
    )
    cluster(db)
    with db() as s:
        for sql in (
            "importance = 1.5",
            "status = 'archived'",
            "category = 'astrology'",
            "available_at = last_updated_at + interval '1 second'",
        ):
            with pytest.raises((IntegrityError, DBAPIError)):
                s.execute(text(f"UPDATE events SET {sql}"))  # noqa: S608
            s.rollback()
        one, two = s.scalars(select(Event).order_by(Event.first_seen_at)).all()
        stolen = s.scalar(select(EventSource.article_id).where(EventSource.event_id == one.id))
        s.add(EventSource(event_id=two.id, article_id=stolen, similarity=1))
        with pytest.raises(IntegrityError):  # an article belongs to one event only
            s.commit()


# --- API ----------------------------------------------------------------------------------------


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


def test_api_lists_events_with_their_articles(db, client):
    news(db, art(1, APPLE_A, 120, outlet="reuters"), art(2, APPLE_B, 60, outlet="ap"),
         art(3, "Fed holds interest rates steady", 30, tickers=("spy",)))  # fmt: skip
    cluster(db)
    rows = client.get("/api/v1/events").json()
    assert [r["title"] for r in rows] == ["Fed holds interest rates steady", APPLE_A]
    apple = rows[1]
    assert len(apple["articles"]) == 2 and apple["tickers"] == [
        {"symbol": "AAPL", "relevance": "1.000"}]  # fmt: skip
    assert apple["horizon"] == "days" and float(apple["importance"]) > 0.3
    assert [r["title"] for r in client.get("/api/v1/events?ticker=aapl").json()] == [APPLE_A]
    assert (
        client.get("/api/v1/events?category=central_bank").json()[0]["category"] == "central_bank"
    )
    assert client.get("/api/v1/events?status=closed").json() == []
    assert client.get("/api/v1/events?limit=0").status_code == 422


def test_api_as_of_rebuilds_the_event_from_what_was_available(db, client):
    news(db, art(1, APPLE_A, 120, outlet="reuters"))
    news(db, art(2, APPLE_B, 60, outlet="ap"), at=NOW + timedelta(hours=3))
    cluster(db, at=NOW + timedelta(hours=3))
    early = client.get("/api/v1/events", params={"as_of": (NOW + timedelta(hours=1)).isoformat()})
    (event,) = early.json()
    assert len(event["articles"]) == 1 and event["score_details"]["articles"] == 1
    assert (
        client.get(
            "/api/v1/events", params={"as_of": (NOW - timedelta(hours=1)).isoformat()}
        ).json()
        == []
    )
    (now_event,) = client.get("/api/v1/events").json()
    assert len(now_event["articles"]) == 2 and float(now_event["importance"]) > float(
        event["importance"]
    )
