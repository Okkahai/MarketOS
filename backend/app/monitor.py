"""Operational health: what should have run, what failed, what is stuck.

Everything is derived from system_runs and provider_failures, so the report cannot drift from
what the jobs actually did. Alerts are returned (for the status page) and logged at ERROR by the
`health_check` job; no external notifier is wired in.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ProviderFailure, SystemRun

STALE_AFTER_INTERVALS = 3  # a job that missed three scheduled runs is stale
STUCK_AFTER = timedelta(hours=1)  # a "running" row this old means the worker died mid-job
FAILURE_WINDOW = timedelta(hours=24)


def expected_jobs(s: Settings) -> dict[str, int]:
    """job_name -> seconds between scheduled runs (the names run_job records)."""
    return {
        "ingest_stock_daily": s.schedule_stock_daily_seconds,
        "ingest_crypto_daily": s.schedule_crypto_daily_seconds,
        "ingest_crypto_1m": s.schedule_crypto_1m_seconds,
        "compute_indicators": s.schedule_indicators_seconds,
        "ingest_news_tiingo_news": s.schedule_news_seconds,
        "ingest_news_sec_edgar": s.schedule_news_seconds,
        "ingest_news_fed_rss": s.schedule_news_seconds,
        "cluster_events": s.schedule_events_seconds,
        "ai_analysis": s.schedule_ai_seconds,
        "paper_cycle": s.schedule_paper_seconds,
        "reconcile": s.schedule_reconcile_seconds,
        "evaluate_signals": s.schedule_evaluate_seconds,
    }


def _alert(level: str, code: str, subject: str, message: str) -> dict[str, str]:
    return {"level": level, "code": code, "subject": subject, "message": message}


def health_report(session: Session, settings: Settings, now: datetime) -> dict[str, Any]:
    alerts: list[dict[str, str]] = []
    jobs = []
    for name, interval in expected_jobs(settings).items():
        finished = (
            select(SystemRun)
            .where(SystemRun.job_name == name, SystemRun.status != "running")
            .order_by(SystemRun.started_at.desc())
        )
        last = session.scalar(finished.limit(1))
        last_ok = session.scalar(finished.where(SystemRun.status != "failed").limit(1))
        row = {
            "job": name,
            "last_status": last.status if last else None,
            "last_started_at": last.started_at if last else None,
            "last_success_at": last_ok.started_at if last_ok else None,
        }
        jobs.append(row)
        if last is None:
            alerts.append(_alert("warning", "never_ran", name, "has not run yet"))
            continue
        if last.status == "failed":
            level = "critical" if name == "reconcile" else "error"
            alerts.append(
                _alert(level, "job_failed", name, f"{last.error_type}: {last.error_message}"[:300])
            )
        ok_at = row["last_success_at"]
        if ok_at is None or now - ok_at > timedelta(seconds=interval * STALE_AFTER_INTERVALS):
            alerts.append(_alert("error", "job_stale", name, f"no success since {ok_at or 'ever'}"))
    for run in session.scalars(
        select(SystemRun).where(
            SystemRun.status == "running", SystemRun.started_at < now - STUCK_AFTER
        )
    ):
        alerts.append(
            _alert("error", "job_stuck", run.job_name, f"still running since {run.started_at}")
        )
    failures = {
        provider: n
        for provider, n in session.execute(
            select(ProviderFailure.provider, func.count())
            .where(ProviderFailure.occurred_at >= now - FAILURE_WINDOW)
            .group_by(ProviderFailure.provider)
        )
    }
    for provider, n in failures.items():
        alerts.append(_alert("warning", "provider_failures", provider, f"{n} failures in 24h"))
    return {
        "as_of": now,
        "ok": not alerts,
        "alerts": alerts,
        "jobs": jobs,
        "failures_24h": failures,
    }
