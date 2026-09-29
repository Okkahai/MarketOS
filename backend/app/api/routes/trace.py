"""One call that explains a position or trade: signal -> what the model saw -> risk verdict ->
orders -> trades -> position. Every hop is a stored, immutable row."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.portfolio import DecisionOut, OrderOut, PositionOut, TradeOut
from app.db.session import get_db
from app.models import (
    AiAnalysis,
    Asset,
    ContextSnapshot,
    Event,
    Order,
    Position,
    RiskDecision,
    Signal,
    Trade,
)

router = APIRouter(prefix="/api/v1", tags=["trace"])


class TraceOut(BaseModel):
    signal: dict[str, Any]
    event: dict[str, Any]
    articles: list[dict[str, Any]]  # exactly what the model was shown
    asset_context: dict[str, Any] | None
    analysis: dict[str, Any]
    portfolio_context: dict[str, Any] | None
    decision: DecisionOut | None
    orders: list[OrderOut]
    trades: list[TradeOut]
    position: PositionOut | None


@router.get("/signals/{signal_id}/trace", response_model=TraceOut)
def trace(signal_id: UUID, db: Annotated[Session, Depends(get_db)]) -> TraceOut:
    row = db.execute(
        select(Signal, Asset, AiAnalysis, ContextSnapshot, Event)
        .join(Asset, Asset.id == Signal.asset_id)
        .join(AiAnalysis, AiAnalysis.id == Signal.analysis_id)
        .join(ContextSnapshot, ContextSnapshot.id == AiAnalysis.context_snapshot_id)
        .join(Event, Event.id == AiAnalysis.event_id)
        .where(Signal.id == signal_id)
    ).first()
    if row is None:
        raise HTTPException(404, "signal not found")
    sig, asset, analysis, snap, event = row
    sym = asset.symbol
    ctx = snap.payload
    asset_ctx = next((a for a in ctx.get("candidate_assets", []) if a.get("symbol") == sym), None)

    d = db.scalar(select(RiskDecision).where(RiskDecision.signal_id == sig.id))
    decision = None
    if d:
        decision = DecisionOut(
            id=str(d.id), signal_id=str(sig.id), symbol=sym, action=sig.action,
            confidence=sig.confidence, decision=d.decision, reasons=d.reasons,
            rules_evaluated=d.rules_evaluated, requested_notional=d.requested_notional,
            approved_notional=d.approved_notional, decided_at=d.decided_at,
        )  # fmt: skip
    orders = [
        OrderOut(
            id=str(o.id),
            symbol=sym,
            side=o.side,
            reason=o.reason,
            status=o.status,
            notional=o.notional,
            quantity=o.quantity,
            signal_time=o.signal_time,
            expires_at=o.expires_at,
            filled_at=o.filled_at,
            signal_id=str(sig.id),
        )  # fmt: skip
        for o in db.scalars(
            select(Order).where(Order.signal_id == sig.id).order_by(Order.created_at)
        )
    ]
    trades = [
        TradeOut(
            id=str(t.id),
            symbol=sym,
            side=t.side,
            reason=t.reason,
            quantity=t.quantity,
            reference_price=t.reference_price,
            price=t.price,
            slippage_bps=t.slippage_bps,
            fee=t.fee,
            cash_change=t.cash_change,
            realized_pnl=t.realized_pnl,
            executed_at=t.executed_at,
            price_ts=t.price_ts,
            signal_id=str(sig.id),
        )  # fmt: skip
        for t in db.scalars(select(Trade).where(Trade.signal_id == sig.id).order_by(Trade.seq))
    ]
    pos = db.scalar(select(Position).where(Position.signal_id == sig.id))
    position = None
    if pos:
        position = PositionOut(
            symbol=sym, quantity=pos.quantity, avg_cost=pos.avg_cost, cost_basis=pos.cost_basis,
            price=None, price_ts=None, market_value=None, unrealized_pnl=None,
            realized_pnl=pos.realized_pnl, stop_price=pos.stop_price,
            target_price=pos.target_price, opened_at=pos.opened_at, signal_id=str(sig.id),
        )  # fmt: skip
    return TraceOut(
        signal={
            "id": str(sig.id), "symbol": sym, "action": sig.action,
            "confidence": str(sig.confidence),
            "time_horizon": sig.time_horizon, "generated_at": sig.generated_at.isoformat(),
            "reference_price": str(sig.reference_price),
            "reference_price_ts": sig.reference_price_ts.isoformat(), "thesis": sig.thesis,
            "bull_case": sig.bull_case, "bear_case": sig.bear_case, "risks": sig.risks,
            "invalidation_conditions": sig.invalidation_conditions,
            "key_catalysts": sig.key_catalysts, "evidence": sig.evidence,
        },
        event={"id": str(event.id), "title": event.title, "category": event.category,
               "importance": str(event.importance), "confidence": str(event.confidence),
               "first_seen_at": event.first_seen_at.isoformat()},  # fmt: skip
        articles=ctx.get("event", {}).get("articles", []),
        asset_context=asset_ctx,
        analysis={
            "id": str(analysis.id), "model": analysis.model,
            "model_version": analysis.model_version, "prompt_version": analysis.prompt_version,
            "as_of": analysis.as_of.isoformat(), "context_sha256": snap.payload_sha256,
        },
        portfolio_context=sig.portfolio_context, decision=decision, orders=orders,
        trades=trades, position=position,
    )  # fmt: skip
