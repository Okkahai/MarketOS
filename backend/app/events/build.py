"""Clusters new articles into events and keeps event rows current. One scheduled job.

Every run is a system_runs row. Nothing here calls a provider or a model.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.core.config import Settings
from app.core.ids import uuid7
from app.events.cluster import Bucket, best_bucket
from app.events.score import METHOD_VERSION, EventState, Member, build_state
from app.jobs.runner import run_job
from app.models import Asset, Event, EventAsset, EventSource, NewsArticle, NewsSource
from app.news.dedup import token_set

logger = logging.getLogger(__name__)

BATCH = 2000  # articles per run; the rest is picked up by the next run
_Q = Decimal("0.001")


def to_member(article: NewsArticle, source_key: str, reliability: Decimal) -> Member:
    outlet = article.raw_payload.get("source")
    publisher = outlet.strip().lower() if isinstance(outlet, str) and outlet.strip() else source_key
    return Member(
        article_id=article.id,
        title=article.title,
        summary=article.summary,
        category=article.category,
        publisher=publisher,
        reliability=reliability,
        published_at=article.published_at,
        available_at=article.available_at,
        tickers=frozenset(article.tickers),
        countries=frozenset(article.countries),
        tokens=token_set(article.title_norm),
        is_duplicate=article.duplicate_of_id is not None,
    )


def load_members(
    session: Session, event_ids: list[uuid.UUID], as_of: datetime | None = None
) -> dict[uuid.UUID, list[Member]]:
    """Members of the given events. With as_of, only articles a decision could have seen."""
    out: dict[uuid.UUID, list[Member]] = defaultdict(list)
    if not event_ids:
        return out
    stmt = (
        select(EventSource.event_id, NewsArticle, NewsSource.key, NewsSource.reliability_weight)
        .join(NewsArticle, NewsArticle.id == EventSource.article_id)
        .join(NewsSource, NewsSource.id == NewsArticle.source_id)
        .where(EventSource.event_id.in_(event_ids))
    )
    if as_of is not None:
        stmt = stmt.where(NewsArticle.available_at <= as_of)
    for event_id, article, key, reliability in session.execute(stmt):
        out[event_id].append(to_member(article, key, reliability))
    return out


def state_as_of(session: Session, event_id: uuid.UUID, as_of: datetime) -> EventState | None:
    """The event as it looked at as_of: built only from articles available by then."""
    members = load_members(session, [event_id], as_of).get(event_id)
    return build_state(members) if members else None


def run_cluster_events(
    session_factory: sessionmaker[Session], settings: Settings, *, clock: Clock | None = None
) -> uuid.UUID:
    clock = clock or LiveClock()
    with run_job(session_factory, "cluster_events", provider=None, clock=clock) as ctx:
        window = timedelta(hours=settings.event_window_hours)
        now = clock.now()
        with session_factory() as session:
            result = cluster_new_articles(session, ctx.run_id, window)
            closed = session.execute(
                update(Event)
                .where(Event.status == "open", Event.last_updated_at < now - window)
                .values(status="closed")
            ).rowcount
            session.commit()
        ctx.items_fetched = result["articles"]
        ctx.items_written = result["articles"]
        ctx.details = {**result, "closed": closed}
        return ctx.run_id


def cluster_new_articles(session: Session, run_id: uuid.UUID, window: timedelta) -> dict:
    rows = session.execute(
        select(NewsArticle, NewsSource.key, NewsSource.reliability_weight)
        .join(NewsSource, NewsSource.id == NewsArticle.source_id)
        .outerjoin(EventSource, EventSource.article_id == NewsArticle.id)
        .where(EventSource.article_id.is_(None))
        .order_by(NewsArticle.published_at, NewsArticle.created_at, NewsArticle.id)
        .limit(BATCH)
    ).all()
    if not rows:
        return {"articles": 0, "new_events": 0, "updated_events": 0}
    members = [to_member(a, key, rel) for a, key, rel in rows]
    original_of = {a.id: a.duplicate_of_id for a, _, _ in rows}

    # Open events are candidates. Their members come from the database once, then grow in memory.
    open_ids = list(session.scalars(select(Event.id).where(Event.status == "open")))
    loaded = load_members(session, open_ids)
    buckets = {
        eid: Bucket(eid, sorted(ms, key=lambda m: m.published_at)) for eid, ms in loaded.items()
    }
    event_of: dict[uuid.UUID, uuid.UUID] = {
        m.article_id: eid for eid, ms in loaded.items() for m in ms
    }
    assigned: list[tuple[uuid.UUID, uuid.UUID, float]] = []  # event, article, similarity
    created: set[uuid.UUID] = set()
    touched: set[uuid.UUID] = set()

    def attach(event_id: uuid.UUID, member: Member, similarity: float) -> None:
        bucket = buckets.get(event_id)
        if bucket is None:  # a duplicate of an article in a closed event
            bucket = buckets[event_id] = Bucket(
                event_id, load_members(session, [event_id])[event_id]
            )
        bucket.members.append(member)
        event_of[member.article_id] = event_id
        assigned.append((event_id, member.article_id, similarity))
        touched.add(event_id)

    # Originals first, then their copies, so a copy always finds its original's event.
    for member in [m for m in members if not m.is_duplicate]:
        found = best_bucket(member, [b for b in buckets.values() if b.members], window)
        if found:
            attach(found[0].event_id, member, found[1])
        else:
            event_id = uuid7()
            buckets[event_id] = Bucket(event_id)
            created.add(event_id)
            attach(event_id, member, 1.0)
    copies = [m for m in members if m.is_duplicate]
    missing = {original_of[m.article_id] for m in copies} - event_of.keys()
    if missing:  # originals clustered in an earlier run into an event that has since closed
        event_of.update(
            session.execute(
                select(EventSource.article_id, EventSource.event_id).where(
                    EventSource.article_id.in_(missing)
                )
            ).tuples()
        )
    for member in copies:
        original_event = event_of.get(original_of[member.article_id])
        if original_event is not None:
            attach(original_event, member, 1.0)
            continue
        event_id = uuid7()  # the original is not in any event: keep the copy visible anyway
        buckets[event_id] = Bucket(event_id)
        created.add(event_id)
        attach(event_id, member, 1.0)

    assets = {a.symbol: a for a in session.scalars(select(Asset))}
    for event_id in touched:
        state = build_state(buckets[event_id].members)
        _write_event(session, event_id, state, assets, run_id, is_new=event_id in created)
    session.flush()
    session.add_all(
        EventSource(event_id=e, article_id=a, similarity=Decimal(str(s)).quantize(_Q))
        for e, a, s in assigned
    )
    session.commit()
    return {
        "articles": len(members),
        "new_events": len(created),
        "updated_events": len(touched - created),
    }


def _write_event(
    session: Session,
    event_id: uuid.UUID,
    state: EventState,
    assets: dict[str, Asset],
    run_id: uuid.UUID,
    *,
    is_new: bool,
) -> None:
    n = state.details["articles"]
    linked = {s: c for s, c in state.ticker_counts.items() if s in assets}
    fields = dict(
        title=state.title,
        summary=state.summary,
        category=state.category,
        importance=state.importance,
        confidence=state.confidence,
        countries=state.countries,
        sectors=sorted({assets[s].sector for s in linked if assets[s].sector}),
        horizon=state.horizon,
        first_seen_at=state.first_seen_at,
        last_updated_at=state.last_updated_at,
        available_at=state.available_at,
        method_version=METHOD_VERSION,
        score_details=state.details,
    )
    if is_new:
        session.add(Event(id=event_id, run_id=run_id, **fields))
    else:
        session.execute(update(Event).where(Event.id == event_id).values(**fields))
        session.execute(delete(EventAsset).where(EventAsset.event_id == event_id))
    session.flush()
    session.add_all(
        EventAsset(
            event_id=event_id,
            asset_id=assets[symbol].id,
            relevance=(Decimal(count) / Decimal(n)).quantize(_Q),
            direction_hint="unknown",
            linked_by="rule",
            rationale=f"tagged in {count} of {n} articles",
        )
        for symbol, count in linked.items()
    )
