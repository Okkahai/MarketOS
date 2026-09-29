import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base


class Event(Base):
    """Something that happened, built from one or more articles.

    The row holds the state as of the latest article. Anything that needs the state at an
    earlier time must recompute it from event_sources joined to news_articles.available_at
    (see app.events.build.state_as_of); the columns here would leak later articles.
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('company', 'earnings', 'central_bank', 'filing', 'macro', "
            "'commodities', 'geopolitics', 'crypto', 'other')",
            name="category_valid",
        ),
        CheckConstraint("importance BETWEEN 0 AND 1", name="importance_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("horizon IN ('intraday', 'days', 'weeks', 'months')", name="horizon_valid"),
        CheckConstraint("status IN ('open', 'closed')", name="status_valid"),
        CheckConstraint("method IN ('rule', 'embedding', 'llm')", name="method_valid"),
        CheckConstraint("available_at <= last_updated_at", name="available_before_updated"),
        Index("ix_events_available_at", "available_at"),
        Index("ix_events_status_updated", "status", "last_updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    importance: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    countries: Mapped[list[str]] = mapped_column(
        ARRAY(String(2)), nullable=False, server_default=text("'{}'")
    )
    sectors: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default=text("'{}'")
    )
    horizon: Mapped[str] = mapped_column(String(10), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    method: Mapped[str] = mapped_column(String(10), nullable=False, server_default="rule")
    method_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # How the score was made: components, article and publisher counts. Auditable, not tuned.
    score_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("system_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventSource(Base):
    """Membership: which articles make up an event. An article belongs to one event."""

    __tablename__ = "event_sources"
    __table_args__ = (UniqueConstraint("article_id", name="uq_event_sources_article"),)

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_articles.id", ondelete="RESTRICT"), primary_key=True
    )
    similarity: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventAsset(Base):
    """An asset an event concerns. Derived from the event's articles; rebuilt on every update."""

    __tablename__ = "event_assets"
    __table_args__ = (
        CheckConstraint("relevance BETWEEN 0 AND 1", name="relevance_range"),
        CheckConstraint("direction_hint IN ('up', 'down', 'mixed', 'unknown')", name="hint_valid"),
        CheckConstraint("linked_by IN ('rule', 'llm')", name="linked_by_valid"),
        Index("ix_event_assets_asset", "asset_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True
    )
    relevance: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    # Phase 4 has no sentiment, so the direction is never guessed.
    direction_hint: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="unknown"
    )
    linked_by: Mapped[str] = mapped_column(String(10), nullable=False, server_default="rule")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
