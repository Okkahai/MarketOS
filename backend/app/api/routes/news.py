"""Read-only news API. Text is plain (already cleaned); links are http(s) only."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import NewsArticle, NewsSource
from app.models.news import CATEGORIES

router = APIRouter(prefix="/api/v1/news", tags=["news"])


class NewsSourceOut(BaseModel):
    key: str
    name: str
    kind: str
    reliability_weight: Decimal
    is_enabled: bool
    terms_note: str


class NewsArticleOut(BaseModel):
    id: str
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime
    available_at: datetime
    category: str
    tickers: list[str]
    countries: list[str]
    duplicate_of_id: str | None
    dedup_reason: str | None


@router.get("/sources", response_model=list[NewsSourceOut])
def list_sources(db: Annotated[Session, Depends(get_db)]) -> list[NewsSource]:
    return list(db.scalars(select(NewsSource).order_by(NewsSource.key)))


@router.get("/articles", response_model=list[NewsArticleOut])
def list_articles(
    db: Annotated[Session, Depends(get_db)],
    ticker: Annotated[str | None, Query(max_length=20)] = None,
    category: Annotated[str | None, Query(pattern="^[a-z_]{1,20}$")] = None,
    source: Annotated[str | None, Query(max_length=50)] = None,
    include_duplicates: bool = False,
    as_of: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[NewsArticleOut]:
    """Newest first. as_of hides anything not yet available then, as a decision would see it."""
    stmt = (
        select(NewsArticle, NewsSource.key)
        .join(NewsSource, NewsSource.id == NewsArticle.source_id)
        .order_by(NewsArticle.published_at.desc(), NewsArticle.id.desc())
        .limit(limit)
    )
    if ticker:
        stmt = stmt.where(NewsArticle.tickers.contains([ticker.upper()]))
    if category in CATEGORIES:
        stmt = stmt.where(NewsArticle.category == category)
    if source:
        stmt = stmt.where(NewsSource.key == source)
    if not include_duplicates:
        stmt = stmt.where(NewsArticle.duplicate_of_id.is_(None))
    if as_of:
        stmt = stmt.where(NewsArticle.available_at <= as_of)
    return [
        NewsArticleOut(
            id=str(a.id), source=key, title=a.title, summary=a.summary, url=a.url,
            published_at=a.published_at, available_at=a.available_at, category=a.category,
            tickers=a.tickers, countries=a.countries,
            duplicate_of_id=str(a.duplicate_of_id) if a.duplicate_of_id else None,
            dedup_reason=a.dedup_reason,
        )
        for a, key in db.execute(stmt)
    ]  # fmt: skip
