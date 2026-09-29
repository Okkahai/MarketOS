import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

CATEGORIES = (
    "company", "earnings", "central_bank", "filing", "macro", "commodities", "geopolitics",
    "crypto", "other",
)  # fmt: skip


class NewsSource(Base):
    __tablename__ = "news_sources"
    __table_args__ = (
        CheckConstraint("kind IN ('api', 'rss', 'filing', 'macro')", name="kind_valid"),
        CheckConstraint("reliability_weight BETWEEN 0 AND 1", name="reliability_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    reliability_weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    terms_note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NewsArticle(Base):
    """One collected item, normalised. Duplicates are kept and point at the first copy collected.

    published_at is the source's claim. collected_at is when MarketOS fetched it. available_at
    is when decisions may use it: never earlier than either.
    """

    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_news_articles_source_external"),
        UniqueConstraint("source_id", "canonical_url", name="uq_news_articles_source_url"),
        CheckConstraint(
            "category IN ('company', 'earnings', 'central_bank', 'filing', 'macro', "
            "'commodities', 'geopolitics', 'crypto', 'other')",
            name="category_valid",
        ),
        CheckConstraint(
            "dedup_reason IS NULL OR duplicate_of_id IS NOT NULL", name="reason_needs_original"
        ),
        CheckConstraint("available_at >= collected_at", name="available_after_collected"),
        Index("ix_news_articles_available_at", "available_at"),
        Index("ix_news_articles_published_at", "published_at"),
        Index("ix_news_articles_content_hash", "content_hash"),
        Index("ix_news_articles_duplicate_of", "duplicate_of_id"),
        Index("ix_news_articles_tickers", "tickers", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    title_norm: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    countries: Mapped[list[str]] = mapped_column(
        ARRAY(String(2)), nullable=False, server_default=text("'{}'")
    )
    companies: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default=text("'{}'")
    )
    tickers: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), nullable=False, server_default=text("'{}'")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("news_articles.id", ondelete="RESTRICT")
    )
    dedup_reason: Mapped[str | None] = mapped_column(String(20))
    # Filled by later phases. Null means "not computed", never a default guess.
    sentiment: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    importance: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("system_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
