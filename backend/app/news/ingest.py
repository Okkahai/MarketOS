"""Scheduled news collection, one run per source.

Same rules as market data: every run is a system_runs row, a failed call is a provider_failures
row, and nothing is invented. A source with no credentials is a skipped run.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.core.config import Settings
from app.jobs.runner import run_job
from app.models import Asset, NewsSource
from app.news.normalize import NewsFetch, normalize_all
from app.news.sources import ensure_sources
from app.news.store import latest_published, store_articles
from app.providers.base import ProviderAuthError, ProviderRateLimited
from app.providers.failures import record_failure, record_rejections

logger = logging.getLogger(__name__)

# since -> fetched articles. Built from a concrete provider in app.jobs.tasks.
NewsFetcher = Callable[[datetime], NewsFetch]
# Re-read a little history each run so items published while we were down or late are caught.
OVERLAP = timedelta(hours=2)


def tracked_symbols(session: Session, provider: str, *classes: str) -> list[str]:
    """Provider-specific symbols of active assets, e.g. Tiingo tickers of the stocks."""
    assets = session.scalars(
        select(Asset).where(Asset.is_active.is_(True), Asset.asset_class.in_(classes))
    ).all()
    return sorted({a.provider_symbols[provider] for a in assets if provider in a.provider_symbols})


def run_news_source(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    source_key: str,
    fetcher: NewsFetcher | None,
    missing_credentials_hint: str = "",
    clock: Clock | None = None,
) -> uuid.UUID:
    clock = clock or LiveClock()
    with run_job(
        session_factory, f"ingest_news_{source_key}", provider=source_key, clock=clock
    ) as ctx:
        if fetcher is None:
            ctx.status = "skipped"
            ctx.details = {"reason": f"{source_key} is not configured. {missing_credentials_hint}"}
            return ctx.run_id
        with session_factory() as session:
            ensure_sources(session)
            source = session.scalars(select(NewsSource).where(NewsSource.key == source_key)).one()
            if not source.is_enabled:
                ctx.status = "skipped"
                ctx.details = {"reason": f"{source_key} is disabled in news_sources"}
                return ctx.run_id
            now = clock.now()
            latest = latest_published(session, source.id)
            since = (
                latest - OVERLAP if latest else now - timedelta(days=settings.news_backfill_days)
            )
            fetched = fetcher(since)

            for subject, exc in fetched.errors:
                record_failure(session, ctx.run_id, source_key, subject, exc, now)
                logger.warning(
                    "news source call failed",
                    extra={"source": source_key, "subject": subject, "error": str(exc)},
                )
            good, rejected = normalize_all(fetched.articles, now)
            rejected = fetched.rejected + rejected
            if rejected:
                record_rejections(
                    session, ctx.run_id, source_key, None, rejected, now, what="articles"
                )
            stats = store_articles(
                session, source_id=source.id, articles=good, run_id=ctx.run_id,
                dedup_window=timedelta(hours=settings.news_dedup_window_hours),
            )  # fmt: skip

        ctx.items_fetched = len(fetched.articles)
        ctx.items_written = stats.written
        ctx.details = {
            "since": since.isoformat(),
            "written": stats.written,
            "duplicates": stats.duplicates,
            "already_stored": stats.already_stored,
            "rejected": len(rejected),
            "errors": len(fetched.errors),
        }
        if any(isinstance(e, ProviderAuthError | ProviderRateLimited) for _, e in fetched.errors):
            ctx.details["aborted"] = "stopped after auth or rate limit error"
        if fetched.errors and not fetched.articles and not stats.already_stored:
            ctx.status = "failed"
        elif fetched.errors or rejected:
            ctx.status = "partial"
        return ctx.run_id
