import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base


class PerformanceEvaluation(Base):
    """How one recommendation did over one horizon, judged only with bars that existed by
    evaluated_at. Immutable: written once, when the horizon has fully elapsed."""

    __tablename__ = "performance_evaluations"
    __table_args__ = (
        UniqueConstraint("signal_id", "horizon", name="signal_horizon"),
        CheckConstraint("horizon IN ('1d', '3d', '7d', '30d')", name="horizon_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    horizon: Mapped[str] = mapped_column(String(3), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_price: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    end_price: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    end_price_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    mfe_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)  # best move
    mae_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)  # worst move
    benchmark_symbol: Mapped[str | None] = mapped_column(String(32))
    benchmark_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    excess_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    direction_correct: Mapped[bool | None] = mapped_column(Boolean)  # null: no directional claim
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
