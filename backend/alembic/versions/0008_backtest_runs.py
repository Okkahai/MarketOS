"""Backtest runs: isolated replay portfolios

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29 11:56:56.145424
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="running", nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_hours", sa.Integer(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_backtest_runs_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )
    op.add_column("portfolios", sa.Column("backtest_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_portfolios_backtest_run_id_backtest_runs"),
        "portfolios",
        "backtest_runs",
        ["backtest_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_signals_backtest_run_id_backtest_runs"),
        "signals",
        "backtest_runs",
        ["backtest_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:

    op.drop_constraint(
        op.f("fk_signals_backtest_run_id_backtest_runs"), "signals", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_portfolios_backtest_run_id_backtest_runs"), "portfolios", type_="foreignkey"
    )
    op.drop_column("portfolios", "backtest_run_id")
    op.drop_table("backtest_runs")
