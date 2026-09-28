"""Liveness and readiness probes.

/health/live answers as long as the process runs.
/health/ready also checks PostgreSQL and Redis and returns 503 if either is down,
so orchestrators stop routing traffic instead of serving half-broken pages.
"""

import logging
import time
from collections.abc import Callable
from typing import Literal

import redis
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class CheckResult(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: int
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckResult]


def check_database() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


def check_redis() -> None:
    timeout = get_settings().health_check_timeout_seconds
    client = redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=timeout, socket_connect_timeout=timeout
    )
    try:
        client.ping()
    finally:
        client.close()


CHECKS: dict[str, Callable[[], None]] = {"database": check_database, "redis": check_redis}


def _run(name: str, check: Callable[[], None]) -> CheckResult:
    started = time.perf_counter()
    try:
        check()
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        logger.warning("readiness check failed", extra={"check": name, "error": repr(exc)})
        # Only the exception type is returned: messages can contain hostnames or credentials.
        return CheckResult(
            status="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=type(exc).__name__,
        )
    return CheckResult(status="ok", latency_ms=int((time.perf_counter() - started) * 1000))


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessResponse)
def ready(response: Response) -> ReadinessResponse:
    results = {name: _run(name, check) for name, check in CHECKS.items()}
    healthy = all(r.status == "ok" for r in results.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if healthy else "degraded", checks=results)
