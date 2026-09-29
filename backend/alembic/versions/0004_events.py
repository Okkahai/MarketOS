"""Events: events, event_sources, event_assets (rule-based clustering)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29 07:17:50.111936
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("importance", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "countries",
            postgresql.ARRAY(sa.String(length=2)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.String(length=100)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("horizon", sa.String(length=10), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("method", sa.String(length=10), server_default="rule", nullable=False),
        sa.Column("method_version", sa.String(length=20), nullable=False),
        sa.Column("score_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('company', 'earnings', 'central_bank', 'filing', 'macro', "
            "'commodities', 'geopolitics', 'crypto', 'other')",
            name=op.f("ck_events_category_valid"),
        ),
        sa.CheckConstraint(
            "horizon IN ('intraday', 'days', 'weeks', 'months')",
            name=op.f("ck_events_horizon_valid"),
        ),
        sa.CheckConstraint(
            "method IN ('rule', 'embedding', 'llm')", name=op.f("ck_events_method_valid")
        ),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_events_status_valid")),
        sa.CheckConstraint(
            "available_at <= last_updated_at", name=op.f("ck_events_available_before_updated")
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_events_confidence_range")),
        sa.CheckConstraint("importance BETWEEN 0 AND 1", name=op.f("ck_events_importance_range")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system_runs.id"],
            name=op.f("fk_events_run_id_system_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_available_at", "events", ["available_at"], unique=False)
    op.create_index(
        "ix_events_status_updated", "events", ["status", "last_updated_at"], unique=False
    )
    op.create_table(
        "event_assets",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("relevance", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("direction_hint", sa.String(length=10), server_default="unknown", nullable=False),
        sa.Column("linked_by", sa.String(length=10), server_default="rule", nullable=False),
        sa.Column("rationale", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint(
            "direction_hint IN ('up', 'down', 'mixed', 'unknown')",
            name=op.f("ck_event_assets_hint_valid"),
        ),
        sa.CheckConstraint(
            "linked_by IN ('rule', 'llm')", name=op.f("ck_event_assets_linked_by_valid")
        ),
        sa.CheckConstraint(
            "relevance BETWEEN 0 AND 1", name=op.f("ck_event_assets_relevance_range")
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_event_assets_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_assets_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", "asset_id", name=op.f("pk_event_assets")),
    )
    op.create_index("ix_event_assets_asset", "event_assets", ["asset_id"], unique=False)
    op.create_table(
        "event_sources",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("similarity", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news_articles.id"],
            name=op.f("fk_event_sources_article_id_news_articles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_sources_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", "article_id", name=op.f("pk_event_sources")),
        sa.UniqueConstraint("article_id", name="uq_event_sources_article"),
    )


def downgrade() -> None:
    op.drop_table("event_sources")
    op.drop_index("ix_event_assets_asset", table_name="event_assets")
    op.drop_table("event_assets")
    op.drop_index("ix_events_status_updated", table_name="events")
    op.drop_index("ix_events_available_at", table_name="events")
    op.drop_table("events")
