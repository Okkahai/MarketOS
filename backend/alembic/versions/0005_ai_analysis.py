"""AI analysis: context_snapshots, ai_analyses, signals (append-only)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29 07:29:34.776674
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("builder_version", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_context_snapshots")),
    )
    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("context_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(length=10), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parsed_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_status", sa.String(length=10), nullable=False),
        sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('triage', 'analysis')", name=op.f("ck_ai_analyses_stage_valid")
        ),
        sa.CheckConstraint(
            "validation_status IN ('valid', 'invalid', 'refused', 'error')",
            name=op.f("ck_ai_analyses_validation_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["context_snapshot_id"],
            ["context_snapshots.id"],
            name=op.f("fk_ai_analyses_context_snapshot_id_context_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_ai_analyses_event_id_events"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system_runs.id"],
            name=op.f("fk_ai_analyses_run_id_system_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analyses")),
    )
    op.create_index("ix_ai_analyses_as_of", "ai_analyses", ["as_of"], unique=False)
    op.create_index(
        "ix_ai_analyses_event", "ai_analyses", ["event_id", "stage", "as_of"], unique=False
    )
    op.create_index("ix_ai_analyses_request_hash", "ai_analyses", ["request_hash"], unique=False)
    op.create_table(
        "signals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("direction", sa.String(length=5), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("time_horizon", sa.String(length=3), nullable=False),
        sa.Column("reference_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("reference_price_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thesis", sa.Text(), server_default="", nullable=False),
        sa.Column("bull_case", sa.Text(), server_default="", nullable=False),
        sa.Column("bear_case", sa.Text(), server_default="", nullable=False),
        sa.Column("key_catalysts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "invalidation_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "supporting_event_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("suggested_position_size_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("suggested_stop_loss_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("suggested_take_profit_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("portfolio_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mode", sa.String(length=10), server_default="live_paper", nullable=False),
        sa.Column("backtest_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL', 'AVOID')",
            name=op.f("ck_signals_action_valid"),
        ),
        sa.CheckConstraint(
            "direction IN ('long', 'flat', 'exit')", name=op.f("ck_signals_direction_valid")
        ),
        sa.CheckConstraint(
            "mode IN ('live_paper', 'backtest')", name=op.f("ck_signals_mode_valid")
        ),
        sa.CheckConstraint(
            "time_horizon IN ('1d', '3d', '7d', '30d')", name=op.f("ck_signals_horizon_valid")
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_signals_confidence_range")),
        sa.CheckConstraint("reference_price > 0", name=op.f("ck_signals_reference_price_positive")),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["ai_analyses.id"],
            name=op.f("fk_signals_analysis_id_ai_analyses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_signals_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(
        "ix_signals_asset_generated", "signals", ["asset_id", "generated_at"], unique=False
    )
    op.create_index("ix_signals_generated", "signals", ["generated_at"], unique=False)
    _append_only()


# The journal must not be rewritten after the fact. TRUNCATE is left open on purpose (test cleanup).
_TABLES = ("context_snapshots", "ai_analyses", "signals")


def _append_only() -> None:
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_index("ix_signals_generated", table_name="signals")
    op.drop_index("ix_signals_asset_generated", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_ai_analyses_request_hash", table_name="ai_analyses")
    op.drop_index("ix_ai_analyses_event", table_name="ai_analyses")
    op.drop_index("ix_ai_analyses_as_of", table_name="ai_analyses")
    op.drop_table("ai_analyses")
    op.drop_table("context_snapshots")
