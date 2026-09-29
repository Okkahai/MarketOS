"""Read-only events API. Every event is shown with the articles it was built from."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.events.build import load_members
from app.events.score import Member, build_state
from app.models import Asset, Event, EventAsset

router = APIRouter(prefix="/api/v1/events", tags=["events"])


class EventArticleOut(BaseModel):
    id: str
    title: str
    publisher: str
    published_at: datetime
    available_at: datetime
    is_duplicate: bool


class EventTickerOut(BaseModel):
    symbol: str
    relevance: Decimal  # share of the event's articles that mention it


class EventOut(BaseModel):
    id: str
    title: str
    summary: str
    category: str
    importance: Decimal
    confidence: Decimal
    horizon: str
    status: str
    countries: list[str]
    tickers: list[EventTickerOut]
    first_seen_at: datetime
    last_updated_at: datetime
    available_at: datetime
    articles: list[EventArticleOut]
    score_details: dict


@router.get("", response_model=list[EventOut])
def list_events(
    db: Annotated[Session, Depends(get_db)],
    ticker: Annotated[str | None, Query(max_length=20)] = None,
    category: Annotated[str | None, Query(pattern="^[a-z_]{1,20}$")] = None,
    status: Literal["open", "closed"] | None = None,
    as_of: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[EventOut]:
    """Newest first. With as_of, each event is rebuilt from the articles available by then, so
    its score and article list are what a decision at that time could have seen."""
    stmt = (
        select(Event)
        .order_by(Event.last_updated_at.desc(), Event.first_seen_at.desc(), Event.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Event.status == status)
    if ticker:
        stmt = stmt.where(
            Event.id.in_(
                select(EventAsset.event_id)
                .join(Asset, Asset.id == EventAsset.asset_id)
                .where(Asset.symbol == ticker.upper())
            )
        )
    if as_of:
        stmt = stmt.where(Event.available_at <= as_of)
    elif category:
        stmt = stmt.where(Event.category == category)
    events = list(db.scalars(stmt))
    members = load_members(db, [e.id for e in events], as_of)

    out = []
    for event in events:
        ms = members.get(event.id)
        if not ms:
            continue
        state = build_state(ms)
        if category and state.category != category:
            continue
        if ticker and ticker.upper() not in state.ticker_counts:
            continue
        out.append(_to_out(event, state, ms))
    out.sort(key=lambda e: (e.last_updated_at, e.first_seen_at, e.id), reverse=True)
    return out


def _to_out(event: Event, state, members: list[Member]) -> EventOut:
    n = len(members)
    return EventOut(
        id=str(event.id),
        title=state.title,
        summary=state.summary,
        category=state.category,
        importance=state.importance,
        confidence=state.confidence,
        horizon=state.horizon,
        status=event.status,
        countries=state.countries,
        tickers=[
            EventTickerOut(symbol=s, relevance=(Decimal(c) / Decimal(n)).quantize(Decimal("0.001")))
            for s, c in state.ticker_counts.items()
        ],
        first_seen_at=state.first_seen_at,
        last_updated_at=state.last_updated_at,
        available_at=state.available_at,
        articles=[
            EventArticleOut(
                id=str(m.article_id),
                title=m.title,
                publisher=m.publisher,
                published_at=m.published_at,
                available_at=m.available_at,
                is_duplicate=m.is_duplicate,
            )
            for m in sorted(members, key=lambda m: m.published_at)
        ],
        score_details=state.details,
    )
