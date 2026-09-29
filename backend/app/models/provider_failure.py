import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base


class ProviderFailure(Base):
    """A failed provider call. A failure leaves a row here and nothing in the data tables."""

    __tablename__ = "provider_failures"
    __table_args__ = (Index("ix_provider_failures_provider_occurred", "provider", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("system_runs.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(300), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(64))  # e.g. the symbol requested
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
