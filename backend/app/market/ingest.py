"""Scheduled market data collection.

Every run is a system_runs row. A failed provider call is a provider_failures row and writes
no bars; the run is marked partial or failed. Nothing is interpolated or invented.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.core.config import Settings
from app.jobs.runner import JobContext, run_job
from app.market.bars import INTERVAL_DELTA, FetchResult
from app.market.repository import StoreStats, latest_stored_ts, store_bars
from app.models import Asset
from app.providers.base import ProviderAuthError, ProviderError, ProviderRateLimited
from app.providers.failures import record_failure, record_rejections

logger = logging.getLogger(__name__)

# (asset, start, end) -> bars. Built from a concrete provider in app.jobs.tasks.
Fetcher = Callable[[Asset, datetime, datetime], FetchResult]


@dataclass
class AssetOutcome:
    fetched: int = 0
    written: int = 0
    revisions: int = 0
    unchanged: int = 0
    not_yet_available: int = 0
    rejected: int = 0


def fetch_window(
    latest: datetime | None, interval: str, now: datetime, settings: Settings
) -> tuple[datetime, datetime]:
    """First run backfills history; later runs re-fetch a short overlap to catch corrections."""
    if latest is None:
        span = (
            timedelta(days=settings.market_history_days)
            if interval == "1d"
            else timedelta(hours=settings.market_intraday_backfill_hours)
        )
        return now - span, now
    overlap = (
        timedelta(days=settings.market_overlap_days)
        if interval == "1d"
        else 30 * INTERVAL_DELTA[interval]
    )
    return latest - overlap, now


def run_ingest(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    job_name: str,
    provider: str,
    interval: str,
    asset_classes: tuple[str, ...],
    fetcher: Fetcher | None,
    missing_credentials_hint: str = "",
    clock: Clock | None = None,
) -> uuid.UUID:
    clock = clock or LiveClock()
    with run_job(session_factory, job_name, provider=provider, clock=clock) as ctx:
        if fetcher is None:
            ctx.status = "skipped"
            ctx.details = {"reason": f"{provider} is not configured. {missing_credentials_hint}"}
            return ctx.run_id
        with session_factory() as session:
            _ingest_assets(
                session, ctx, settings, provider, interval, asset_classes, fetcher, clock
            )
        return ctx.run_id


def _ingest_assets(
    session: Session,
    ctx: JobContext,
    settings: Settings,
    provider: str,
    interval: str,
    asset_classes: tuple[str, ...],
    fetcher: Fetcher,
    clock: Clock,
) -> None:
    assets = session.scalars(
        select(Asset)
        .where(Asset.is_active.is_(True), Asset.asset_class.in_(asset_classes))
        .order_by(Asset.symbol)
    ).all()
    outcomes: dict[str, dict] = {}
    failed = succeeded = fetched = stored = 0
    aborted_reason: str | None = None

    for asset in assets:
        if provider not in asset.provider_symbols:
            outcomes[asset.symbol] = {"skipped": f"no {provider} symbol configured"}
            continue
        now = clock.now()
        try:
            start, end = fetch_window(
                latest_stored_ts(session, asset.id, interval, provider), interval, now, settings
            )
            result = fetcher(asset, start, end)
            stats = store_bars(
                session, asset_id=asset.id, interval=interval, provider=provider,
                bars=result.bars, run_id=ctx.run_id, now=now,
            )  # fmt: skip
        except ProviderError as exc:
            session.rollback()
            failed += 1
            outcomes[asset.symbol] = {"error": f"{type(exc).__name__}: {exc}"}
            record_failure(session, ctx.run_id, provider, asset.symbol, exc, now)
            logger.warning(
                "provider call failed",
                extra={"provider": provider, "symbol": asset.symbol, "error": str(exc)},
            )
            if isinstance(exc, ProviderAuthError | ProviderRateLimited):
                aborted_reason = f"stopped after {type(exc).__name__}"
                break
            continue

        succeeded += 1
        fetched += len(result.bars)
        stored += stats.written + stats.revisions
        outcomes[asset.symbol] = asdict(_outcome(result, stats))
        if result.rejected:
            record_rejections(
                session, ctx.run_id, provider, asset.symbol, result.rejected, now, what="bars"
            )

    ctx.items_fetched = fetched
    ctx.items_written = stored
    ctx.details = {"interval": interval, "assets": outcomes}
    if aborted_reason:
        ctx.details["aborted"] = aborted_reason
    if failed and not succeeded:
        ctx.status = "failed"
    elif failed or any(o.get("rejected") for o in outcomes.values()):
        ctx.status = "partial"


def _outcome(result: FetchResult, stats: StoreStats) -> AssetOutcome:
    return AssetOutcome(
        fetched=len(result.bars), written=stats.written, revisions=stats.revisions,
        unchanged=stats.unchanged, not_yet_available=stats.not_yet_available,
        rejected=len(result.rejected),
    )  # fmt: skip
