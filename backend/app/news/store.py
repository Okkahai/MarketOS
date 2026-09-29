"""Writes normalised articles and marks duplicates. Rows are never updated or deleted here."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import NewsArticle
from app.news.dedup import Candidate, find_duplicate
from app.news.normalize import NormalizedArticle

POOL_LIMIT = 5000


@dataclass
class StoreStats:
    written: int = 0
    duplicates: int = 0  # written, but marked as a copy of an earlier article
    already_stored: int = 0


def store_articles(
    session: Session,
    *,
    source_id: uuid.UUID,
    articles: list[NormalizedArticle],
    run_id: uuid.UUID,
    dedup_window: timedelta,
) -> StoreStats:
    stats = StoreStats()
    if not articles:
        return stats
    ordered = sorted(articles, key=lambda a: (a.published_at, a.external_id))
    since = ordered[0].published_at - dedup_window
    pool = [
        Candidate(id=r.id, canonical_url=r.canonical_url, title_norm=r.title_norm,
                  text_dedup=r.category != "filing")
        for r in session.execute(
            select(NewsArticle.id, NewsArticle.canonical_url, NewsArticle.title_norm,
                   NewsArticle.category)
            .where(NewsArticle.duplicate_of_id.is_(None), NewsArticle.published_at >= since)
            .order_by(NewsArticle.published_at, NewsArticle.created_at)
            .limit(POOL_LIMIT)
        )
    ]  # fmt: skip

    for art in ordered:
        match = find_duplicate(
            canonical_url=art.canonical_url,
            title_norm=art.title_norm,
            text_dedup=art.text_dedup,
            pool=pool,
        )
        new_id = session.execute(
            insert(NewsArticle)
            .values(
                source_id=source_id,
                external_id=art.external_id,
                url=art.url,
                canonical_url=art.canonical_url,
                title=art.title,
                title_norm=art.title_norm,
                summary=art.summary,
                published_at=art.published_at,
                collected_at=art.collected_at,
                available_at=art.available_at,
                category=art.category,
                countries=art.countries,
                companies=art.companies,
                tickers=art.tickers,
                content_hash=art.content_hash,
                duplicate_of_id=match[0] if match else None,
                dedup_reason=match[1] if match else None,
                raw_payload=art.raw_payload,
                run_id=run_id,
            )
            .on_conflict_do_nothing()
            .returning(NewsArticle.id)
        ).scalar_one_or_none()
        if new_id is None:
            stats.already_stored += 1
            continue
        stats.written += 1
        if match:
            stats.duplicates += 1
        else:
            pool.append(Candidate(new_id, art.canonical_url, art.title_norm, art.text_dedup))
    session.commit()
    return stats


def latest_published(session: Session, source_id: uuid.UUID) -> datetime | None:
    return session.scalar(
        select(NewsArticle.published_at)
        .where(NewsArticle.source_id == source_id)
        .order_by(NewsArticle.published_at.desc())
        .limit(1)
    )
