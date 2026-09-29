"""Writes provider_failures rows. Shared by every ingest job."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from app.market.bars import RejectedRow
from app.models import ProviderFailure
from app.providers.base import ProviderError


def record_failure(
    session: Session,
    run_id: uuid.UUID,
    provider: str,
    subject: str | None,
    exc: ProviderError,
    now: datetime,
) -> None:
    session.add(
        ProviderFailure(
            run_id=run_id,
            provider=provider,
            endpoint=exc.endpoint or "unknown",
            subject=subject,
            http_status=exc.http_status,
            error_type=type(exc).__name__,
            error=str(exc)[:2000],
            retry_count=exc.retry_count,
            occurred_at=now,
        )  # fmt: skip
    )
    session.commit()


def record_rejections(
    session: Session,
    run_id: uuid.UUID,
    provider: str,
    subject: str | None,
    rejected: Sequence[RejectedRow],
    now: datetime,
    *,
    what: str,
) -> None:
    """One row per batch: the count and the first reason, so a broken feed is visible."""
    first = rejected[0]
    session.add(
        ProviderFailure(
            run_id=run_id,
            provider=provider,
            endpoint=f"{what} validation",
            subject=subject,
            error_type=f"Rejected{what.title()}",
            occurred_at=now,
            error=f"{len(rejected)} rows rejected. First: {first.reason} | {first.raw}"[:2000],
        )  # fmt: skip
    )
    session.commit()
