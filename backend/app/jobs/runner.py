"""Every background job runs inside run_job(), which records a system_runs row.

A job that raises is recorded as failed with the error; the exception is re-raised
so Celery can apply its retry policy. Nothing is swallowed silently.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.models.system_run import SystemRun

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    run_id: Any
    items_fetched: int | None = None
    items_written: int | None = None
    status: str | None = None  # set to "partial" or "skipped" to override success
    details: dict[str, Any] = field(default_factory=dict)


@contextmanager
def run_job(
    session_factory: sessionmaker[Session],
    job_name: str,
    *,
    provider: str | None = None,
    clock: Clock | None = None,
) -> Iterator[JobContext]:
    clock = clock or LiveClock()
    with session_factory() as session:
        run = SystemRun(
            job_name=job_name,
            status="running",
            provider=provider,
            started_at=clock.now(),
            details={},
        )
        session.add(run)
        session.commit()
        ctx = JobContext(run_id=run.id)
        logger.info("job started", extra={"job": job_name, "run_id": str(run.id)})
        try:
            yield ctx
        except Exception as exc:
            run.status = "failed"
            run.error_type = type(exc).__name__
            run.error_message = str(exc)[:2000]
            _finish(session, run, ctx, clock)
            logger.exception("job failed", extra={"job": job_name, "run_id": str(run.id)})
            raise
        run.status = ctx.status or "succeeded"
        _finish(session, run, ctx, clock)
        logger.info(
            "job finished", extra={"job": job_name, "run_id": str(run.id), "status": run.status}
        )


def _finish(session: Session, run: SystemRun, ctx: JobContext, clock: Clock) -> None:
    run.finished_at = clock.now()
    run.items_fetched = ctx.items_fetched
    run.items_written = ctx.items_written
    run.details = ctx.details
    session.commit()
