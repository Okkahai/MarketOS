"""Failure injection: broken jobs must show up as alerts, never as silence."""

# ruff: noqa: F811
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import FixedClock
from app.core.config import Settings
from app.jobs.runner import run_job
from app.models import ProviderFailure, SystemRun
from app.monitor import expected_jobs, health_report
from tests.integration.test_trading import T0, db, pytestmark  # noqa: F401


def ran(db, name, at, *, fail=False):
    try:
        with run_job(db, name, clock=FixedClock(at)):
            if fail:
                raise RuntimeError("provider exploded")
    except RuntimeError:
        pass


def codes(db, now):
    with db() as s:
        rep = health_report(s, Settings(), now)
    return {(a["code"], a["subject"]) for a in rep["alerts"]}, rep


def test_healthy_when_every_job_ran_recently(db):
    for name in expected_jobs(Settings()):
        ran(db, name, T0)
    found, rep = codes(db, T0 + timedelta(minutes=1))
    assert found == set() and rep["ok"]


def test_nothing_ran_is_reported_not_hidden(db):
    found, _ = codes(db, T0)
    assert ("never_ran", "paper_cycle") in found


def test_failed_stale_and_stuck_jobs_are_alerts(db):
    for name in expected_jobs(Settings()):
        ran(db, name, T0)
    ran(db, "reconcile", T0 + timedelta(minutes=5), fail=True)
    ran(db, "paper_cycle", T0 + timedelta(minutes=5), fail=True)
    with db() as s:  # a worker that died mid-job leaves a running row behind
        s.add(SystemRun(job_name="ai_analysis", status="running", started_at=T0, details={}))
        s.add(ProviderFailure(run_id=s.scalar(select(SystemRun.id).limit(1)), provider="tiingo",
                              endpoint="x", error_type="HTTPStatusError", error="429",
                              occurred_at=T0))  # fmt: skip
        s.commit()
    found, rep = codes(db, T0 + timedelta(hours=2))
    assert ("job_failed", "reconcile") in found and ("job_failed", "paper_cycle") in found
    assert ("job_stale", "paper_cycle") in found  # 2h > 3 x 300s with no success since T0
    assert ("job_stuck", "ai_analysis") in found
    assert ("provider_failures", "tiingo") in found
    assert next(a for a in rep["alerts"] if a["subject"] == "reconcile")["level"] == "critical"
    assert not rep["ok"]


def test_health_endpoint_and_security_headers(db):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    def override():
        with db() as s:
            yield s

    app.dependency_overrides[get_db] = override
    r = TestClient(app).get("/api/v1/system/health")
    assert r.status_code == 200 and r.json()["ok"] is False  # nothing has ever run
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
