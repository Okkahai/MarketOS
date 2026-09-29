"""Create system_runs: one row per background job execution.

Revision ID: 0001
Revises:
Create Date: 2026-09-28 23:32:18.348973
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("items_fetched", sa.Integer(), nullable=True),
        sa.Column("items_written", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'skipped')",
            name=op.f("ck_system_runs_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_runs")),
    )
    op.create_index(
        "ix_system_runs_job_started", "system_runs", ["job_name", "started_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_system_runs_job_started", table_name="system_runs")
    op.drop_table("system_runs")
