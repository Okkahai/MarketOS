import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

ACTIONS = ("STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL", "AVOID")


class ContextSnapshot(Base):
    """Exactly what the model was shown. Immutable (database trigger): it is the audit record."""

    __tablename__ = "context_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    builder_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiAnalysis(Base):
    """One model call and what came back, including calls that failed validation. Immutable."""

    __tablename__ = "ai_analyses"
    __table_args__ = (
        CheckConstraint("stage IN ('triage', 'analysis')", name="stage_valid"),
        CheckConstraint(
            "validation_status IN ('valid', 'invalid', 'refused', 'error')",
            name="validation_status_valid",
        ),
        Index("ix_ai_analyses_as_of", "as_of"),
        Index("ix_ai_analyses_event", "event_id", "stage", "as_of"),
        Index("ix_ai_analyses_request_hash", "request_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    context_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("context_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(10), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100))  # what the API reported
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parsed_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(String(10), nullable=False)
    validation_errors: Mapped[list[str] | None] = mapped_column(JSONB)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default="0"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("system_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Signal(Base):
    """The decision journal: one row per asset recommendation, kept whether or not it trades."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "action IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL', 'AVOID')",
            name="action_valid",
        ),
        CheckConstraint("direction IN ('long', 'flat', 'exit')", name="direction_valid"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("time_horizon IN ('1d', '3d', '7d', '30d')", name="horizon_valid"),
        CheckConstraint("mode IN ('live_paper', 'backtest')", name="mode_valid"),
        CheckConstraint("reference_price > 0", name="reference_price_positive"),
        Index("ix_signals_asset_generated", "asset_id", "generated_at"),
        Index("ix_signals_generated", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_analyses.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(3), nullable=False)
    # The last price the model was shown, and when that bar became usable.
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    reference_price_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    bull_case: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    bear_case: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    key_catalysts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    invalidation_conditions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    supporting_event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    suggested_position_size_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    suggested_stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    suggested_take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    # Filled by Phase 6 when a portfolio exists; null means "no portfolio yet", never a guess.
    portfolio_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, server_default="live_paper")
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
