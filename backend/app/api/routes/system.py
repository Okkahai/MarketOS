import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import APP_VERSION, get_settings
from app.db.session import get_db
from app.models import SystemRun

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class SystemInfo(BaseModel):
    version: str
    environment: str
    trading_mode: str
    base_currency: str
    paper_initial_capital: str
    providers_configured: dict[str, bool]


@router.get("/info", response_model=SystemInfo)
def info() -> SystemInfo:
    settings = get_settings()
    return SystemInfo(
        version=APP_VERSION,
        environment=settings.app_env,
        trading_mode=settings.trading_mode,
        base_currency=settings.base_currency,
        # Decimal as a string so no client parses money as a float by accident.
        paper_initial_capital=str(settings.paper_initial_capital),
        providers_configured=settings.provider_status(),
    )


class SystemRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_name: str
    status: str
    provider: str | None
    started_at: datetime
    finished_at: datetime | None
    items_fetched: int | None
    items_written: int | None
    error_type: str | None
    error_message: str | None


@router.get("/runs", response_model=list[SystemRunOut])
def recent_runs(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    job_name: Annotated[str | None, Query(max_length=100)] = None,
) -> list[SystemRun]:
    """Most recent job executions, failures included, newest first."""
    query = select(SystemRun).order_by(SystemRun.started_at.desc()).limit(limit)
    if job_name:
        query = query.where(SystemRun.job_name == job_name)
    return list(db.scalars(query))
