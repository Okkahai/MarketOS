"""Market data: assets, market_prices (append-only), indicator_values, provider_failures.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29 06:31:18.874995
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("asset_class", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("exchange", sa.String(length=50), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column(
            "provider_symbols",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_benchmark", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "asset_class IN ('stock', 'etf', 'crypto')", name=op.f("ck_assets_asset_class_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("symbol", name=op.f("uq_assets_symbol")),
    )
    op.create_table(
        "indicator_values",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("interval", sa.String(length=3), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("computed_from_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code_version", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_indicator_values_asset_id_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_indicator_values")),
        sa.UniqueConstraint(
            "asset_id", "interval", "ts", "name", "code_version", name="uq_indicator_values_point"
        ),
    )
    op.create_table(
        "market_prices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("interval", sa.String(length=3), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("high", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("low", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("adj_close", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("volume", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "interval IN ('1m', '5m', '1h', '1d')", name=op.f("ck_market_prices_interval_valid")
        ),
        sa.CheckConstraint(
            "low > 0 AND high >= low AND open BETWEEN low AND high AND close BETWEEN low AND high",
            name=op.f("ck_market_prices_ohlc_consistent"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_market_prices_revision_non_negative")),
        sa.CheckConstraint("volume >= 0", name=op.f("ck_market_prices_volume_non_negative")),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_market_prices_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system_runs.id"],
            name=op.f("fk_market_prices_run_id_system_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_prices")),
        sa.UniqueConstraint(
            "asset_id", "interval", "ts", "provider", "revision", name="uq_market_prices_bar"
        ),
    )
    op.create_index(
        "ix_market_prices_asset_interval_available",
        "market_prices",
        ["asset_id", "interval", "available_at"],
        unique=False,
    )
    op.create_table(
        "provider_failures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("endpoint", sa.String(length=300), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system_runs.id"],
            name=op.f("fk_provider_failures_run_id_system_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_failures")),
    )
    op.create_index(
        "ix_provider_failures_provider_occurred",
        "provider_failures",
        ["provider", "occurred_at"],
        unique=False,
    )

    # Raw bars are history: corrections are new revisions, never edits or deletes.
    # TRUNCATE is not covered on purpose (test cleanup, controlled maintenance).
    op.execute(
        """
        CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% on % is not allowed: table is append-only', TG_OP, TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER market_prices_append_only
        BEFORE UPDATE OR DELETE ON market_prices
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER market_prices_append_only ON market_prices")
    op.execute("DROP FUNCTION forbid_mutation()")
    op.drop_index("ix_provider_failures_provider_occurred", table_name="provider_failures")
    op.drop_table("provider_failures")
    op.drop_index("ix_market_prices_asset_interval_available", table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_table("indicator_values")
    op.drop_table("assets")
