"""Runs against a real PostgreSQL and Redis. Set TEST_DATABASE_URL and TEST_REDIS_URL."""

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.core.clock import FixedClock
from app.jobs.runner import run_job
from app.models import SystemRun

DB_URL = os.environ.get("TEST_DATABASE_URL")
REDIS_URL = os.environ.get("TEST_REDIS_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _alembic() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    return cfg


@pytest.fixture
def migrated():
    cfg = _alembic()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(DB_URL)
    yield engine
    engine.dispose()
    command.downgrade(cfg, "base")


def test_migrations_round_trip(migrated):
    assert "system_runs" in inspect(migrated).get_table_names()
    command.downgrade(_alembic(), "base")
    assert "system_runs" not in inspect(migrated).get_table_names()
    command.upgrade(_alembic(), "head")


def test_run_job_records_success(migrated):
    factory = sessionmaker(bind=migrated)
    clock = FixedClock(datetime(2026, 9, 28, 12, 0, tzinfo=UTC))
    with run_job(factory, "unit-job", provider="tiingo", clock=clock) as ctx:
        ctx.items_fetched = 3
        ctx.items_written = 2
    with factory() as s:
        run = s.scalars(select(SystemRun)).one()
    assert (run.status, run.provider, run.items_fetched, run.items_written) == (
        "succeeded",
        "tiingo",
        3,
        2,
    )
    assert run.finished_at == clock.now()


def test_run_job_records_failure_and_reraises(migrated):
    factory = sessionmaker(bind=migrated)
    with pytest.raises(RuntimeError), run_job(factory, "broken-job"):
        raise RuntimeError("provider returned 500")
    with factory() as s:
        run = s.scalars(select(SystemRun)).one()
    assert run.status == "failed"
    assert run.error_type == "RuntimeError"
    assert run.error_message == "provider returned 500"


def test_run_job_partial_status(migrated):
    factory = sessionmaker(bind=migrated)
    with run_job(factory, "multi-provider") as ctx:
        ctx.status = "partial"
        ctx.details = {"failed_providers": ["alpha_vantage"]}
    with factory() as s:
        run = s.scalars(select(SystemRun)).one()
    assert run.status == "partial"
    assert run.details == {"failed_providers": ["alpha_vantage"]}


def test_invalid_status_rejected_by_database(migrated):
    from sqlalchemy.exc import IntegrityError

    factory = sessionmaker(bind=migrated)
    with factory() as s, pytest.raises(IntegrityError):
        s.add(SystemRun(job_name="x", status="done", started_at=datetime.now(UTC), details={}))
        s.commit()


@pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL not set")
def test_ready_against_real_services(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    from app.main import create_app

    response = TestClient(create_app()).get("/health/ready")
    assert response.status_code == 200, response.text


def test_ready_reports_unreachable_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("HEALTH_CHECK_TIMEOUT_SECONDS", "1")
    from app.main import create_app

    response = TestClient(create_app()).get("/health/ready")
    body = response.json()
    assert response.status_code == 503
    assert body["checks"]["database"]["status"] == "error"
    assert body["checks"]["redis"]["status"] == "error"


def test_runs_endpoint_lists_newest_first_including_failures(migrated, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    factory = sessionmaker(bind=migrated)
    clock = FixedClock(datetime(2026, 9, 28, 12, 0, tzinfo=UTC))
    with run_job(factory, "older", clock=clock):
        pass
    clock.advance_to(datetime(2026, 9, 28, 13, 0, tzinfo=UTC))
    with pytest.raises(ValueError), run_job(factory, "newer", clock=clock):
        raise ValueError("bad payload")
    from app.main import create_app

    client = TestClient(create_app())
    runs = client.get("/api/v1/system/runs").json()
    assert [r["job_name"] for r in runs] == ["newer", "older"]
    assert runs[0]["status"] == "failed"
    assert (
        client.get("/api/v1/system/runs", params={"job_name": "older"}).json()[0]["status"]
        == "succeeded"
    )
    assert client.get("/api/v1/system/runs", params={"limit": 0}).status_code == 422
