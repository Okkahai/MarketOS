import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

INTERVALS = ("1m", "5m", "1h", "1d")


class MarketPrice(Base):
    """Raw OHLCV bars, append-only. A provider correction is a new row with a higher revision.

    ts is the bar's start (stocks' daily bars are labelled with the trading date at 00:00 UTC).
    available_at is when the bar may be used by decisions: bar close, or later for stocks.
    """

    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "interval", "ts", "provider", "revision", name="uq_market_prices_bar"
        ),
        Index("ix_market_prices_asset_interval_available", "asset_id", "interval", "available_at"),
        CheckConstraint("interval IN ('1m', '5m', '1h', '1d')", name="interval_valid"),
        CheckConstraint(
            "low > 0 AND high >= low AND open BETWEEN low AND high AND close BETWEEN low AND high",
            name="ohlc_consistent",
        ),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
        CheckConstraint("revision >= 0", name="revision_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    interval: Mapped[str] = mapped_column(String(3), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("system_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
