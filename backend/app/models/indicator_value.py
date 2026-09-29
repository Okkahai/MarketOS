import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base


class IndicatorValue(Base):
    """Derived, recomputable indicator values. Never read by accounting.

    Decisions and backtests compute indicators from point-in-time bars instead of reading
    this table; it exists so the dashboard does not recompute on every request.
    """

    __tablename__ = "indicator_values"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "interval", "ts", "name", "code_version", name="uq_indicator_values_point"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    interval: Mapped[str] = mapped_column(String(3), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    computed_from_available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    code_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
