"""News: news_sources and news_articles (normalised, duplicates linked to the first copy).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29 06:49:48.916808
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("reliability_weight", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("terms_note", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('api', 'rss', 'filing', 'macro')", name=op.f("ck_news_sources_kind_valid")
        ),
        sa.CheckConstraint(
            "reliability_weight BETWEEN 0 AND 1", name=op.f("ck_news_sources_reliability_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_sources")),
        sa.UniqueConstraint("key", name=op.f("uq_news_sources_key")),
    )
    op.create_table(
        "news_articles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("canonical_url", sa.String(length=2000), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("title_norm", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column(
            "countries",
            postgresql.ARRAY(sa.String(length=2)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "companies",
            postgresql.ARRAY(sa.String(length=100)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "tickers",
            postgresql.ARRAY(sa.String(length=20)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("duplicate_of_id", sa.UUID(), nullable=True),
        sa.Column("dedup_reason", sa.String(length=20), nullable=True),
        sa.Column("sentiment", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("importance", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("ck_news_articles_category_valid"),
        ),
        sa.CheckConstraint(
            "available_at >= collected_at", name=op.f("ck_news_articles_available_after_collected")
        ),
        sa.CheckConstraint(
            "dedup_reason IS NULL OR duplicate_of_id IS NOT NULL",
            name=op.f("ck_news_articles_reason_needs_original"),
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id"],
            ["news_articles.id"],
            name=op.f("fk_news_articles_duplicate_of_id_news_articles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system_runs.id"],
            name=op.f("fk_news_articles_run_id_system_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["news_sources.id"],
            name=op.f("fk_news_articles_source_id_news_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_articles")),
        sa.UniqueConstraint("source_id", "canonical_url", name="uq_news_articles_source_url"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_news_articles_source_external"),
    )
    op.create_index(
        "ix_news_articles_available_at", "news_articles", ["available_at"], unique=False
    )
    op.create_index(
        "ix_news_articles_content_hash", "news_articles", ["content_hash"], unique=False
    )
    op.create_index(
        "ix_news_articles_duplicate_of", "news_articles", ["duplicate_of_id"], unique=False
    )
    op.create_index(
        "ix_news_articles_published_at", "news_articles", ["published_at"], unique=False
    )
    op.create_index(
        "ix_news_articles_tickers",
        "news_articles",
        ["tickers"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_news_articles_tickers", table_name="news_articles", postgresql_using="gin")
    op.drop_index("ix_news_articles_published_at", table_name="news_articles")
    op.drop_index("ix_news_articles_duplicate_of", table_name="news_articles")
    op.drop_index("ix_news_articles_content_hash", table_name="news_articles")
    op.drop_index("ix_news_articles_available_at", table_name="news_articles")
    op.drop_table("news_articles")
    op.drop_table("news_sources")
