"""Read-only view of the AI journal: signals, every model call, and spend."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import LiveClock
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AiAnalysis, Asset, ContextSnapshot, Event, Signal

router = APIRouter(prefix="/api/v1", tags=["ai"])


class SignalOut(BaseModel):
    id: str
    analysis_id: str
    symbol: str
    generated_at: datetime
    action: str
    direction: str
    confidence: Decimal
    time_horizon: str
    reference_price: Decimal
    reference_price_ts: datetime
    thesis: str
    bull_case: str
    bear_case: str
    key_catalysts: list[str]
    risks: list[str]
    invalidation_conditions: list[str]
    evidence: list[dict]
    suggested_position_size_pct: Decimal | None
    suggested_stop_loss_pct: Decimal | None
    suggested_take_profit_pct: Decimal | None
    event_id: str
    event_title: str


class AnalysisOut(BaseModel):
    id: str
    event_id: str
    event_title: str
    stage: str
    as_of: datetime
    model: str
    model_version: str | None
    prompt_version: str
    validation_status: str
    validation_errors: list[str] | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    latency_ms: int


class AnalysisDetail(AnalysisOut):
    raw_output: dict | None
    parsed_output: dict | None
    context_payload_sha256: str
    context_builder_version: str
    context: dict


class UsageOut(BaseModel):
    day: str
    spent_usd: Decimal
    budget_usd: Decimal
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int


@router.get("/signals", response_model=list[SignalOut])
def list_signals(
    db: Annotated[Session, Depends(get_db)],
    symbol: Annotated[str | None, Query(max_length=32)] = None,
    action: Annotated[str | None, Query(pattern="^[A-Z_]{1,12}$")] = None,
    as_of: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SignalOut]:
    stmt = (
        select(Signal, Asset.symbol, AiAnalysis.event_id, Event.title)
        .join(Asset, Asset.id == Signal.asset_id)
        .join(AiAnalysis, AiAnalysis.id == Signal.analysis_id)
        .join(Event, Event.id == AiAnalysis.event_id)
        .where(Signal.mode == "live_paper")  # backtest signals are shown on their own pages
        .order_by(Signal.generated_at.desc(), Signal.id.desc())
        .limit(limit)
    )
    if symbol:
        stmt = stmt.where(Asset.symbol == symbol.upper())
    if action:
        stmt = stmt.where(Signal.action == action)
    if as_of:
        stmt = stmt.where(Signal.generated_at <= as_of)
    return [
        SignalOut(
            id=str(s.id), analysis_id=str(s.analysis_id), symbol=sym, generated_at=s.generated_at,
            action=s.action, direction=s.direction, confidence=s.confidence,
            time_horizon=s.time_horizon, reference_price=s.reference_price,
            reference_price_ts=s.reference_price_ts, thesis=s.thesis, bull_case=s.bull_case,
            bear_case=s.bear_case, key_catalysts=s.key_catalysts, risks=s.risks,
            invalidation_conditions=s.invalidation_conditions, evidence=s.evidence,
            suggested_position_size_pct=s.suggested_position_size_pct,
            suggested_stop_loss_pct=s.suggested_stop_loss_pct,
            suggested_take_profit_pct=s.suggested_take_profit_pct,
            event_id=str(event_id), event_title=title,
        )
        for s, sym, event_id, title in db.execute(stmt)
    ]  # fmt: skip


def _analysis_out(a: AiAnalysis, title: str) -> dict:
    return dict(
        id=str(a.id), event_id=str(a.event_id), event_title=title, stage=a.stage, as_of=a.as_of,
        model=a.model, model_version=a.model_version, prompt_version=a.prompt_version,
        validation_status=a.validation_status, validation_errors=a.validation_errors,
        input_tokens=a.input_tokens, output_tokens=a.output_tokens,
        estimated_cost_usd=a.estimated_cost_usd, latency_ms=a.latency_ms,
    )  # fmt: skip


@router.get("/ai/analyses", response_model=list[AnalysisOut])
def list_analyses(
    db: Annotated[Session, Depends(get_db)],
    status: Annotated[str | None, Query(pattern="^[a-z]{1,10}$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AnalysisOut]:
    stmt = (
        select(AiAnalysis, Event.title)
        .join(Event, Event.id == AiAnalysis.event_id)
        .order_by(AiAnalysis.as_of.desc(), AiAnalysis.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(AiAnalysis.validation_status == status)
    return [AnalysisOut(**_analysis_out(a, title)) for a, title in db.execute(stmt)]


@router.get("/ai/analyses/{analysis_id}", response_model=AnalysisDetail)
def get_analysis(analysis_id: UUID, db: Annotated[Session, Depends(get_db)]) -> AnalysisDetail:
    row = db.execute(
        select(AiAnalysis, Event.title, ContextSnapshot)
        .join(Event, Event.id == AiAnalysis.event_id)
        .join(ContextSnapshot, ContextSnapshot.id == AiAnalysis.context_snapshot_id)
        .where(AiAnalysis.id == analysis_id)
    ).first()
    if row is None:
        raise HTTPException(404, "analysis not found")
    a, title, snap = row
    return AnalysisDetail(
        **_analysis_out(a, title), raw_output=a.raw_output, parsed_output=a.parsed_output,
        context_payload_sha256=snap.payload_sha256, context_builder_version=snap.builder_version,
        context=snap.payload,
    )  # fmt: skip


@router.get("/ai/usage", response_model=UsageOut)
def usage(db: Annotated[Session, Depends(get_db)]) -> UsageOut:
    """Today's (UTC) model calls and estimated spend against the daily budget."""
    now = LiveClock().now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spent, calls, failed, tin, tout = db.execute(
        select(
            func.coalesce(func.sum(AiAnalysis.estimated_cost_usd), 0),
            func.count(),
            func.count().filter(AiAnalysis.validation_status != "valid"),
            func.coalesce(func.sum(AiAnalysis.input_tokens), 0),
            func.coalesce(func.sum(AiAnalysis.output_tokens), 0),
        ).where(AiAnalysis.as_of >= start)
    ).one()
    return UsageOut(
        day=start.date().isoformat(), spent_usd=Decimal(spent),
        budget_usd=get_settings().ai_daily_budget_usd, calls=calls, failed_calls=failed,
        input_tokens=int(tin), output_tokens=int(tout),
    )  # fmt: skip
