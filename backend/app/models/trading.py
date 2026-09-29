import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

MONEY = Numeric(20, 8)
QTY = Numeric(28, 10)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Portfolio(Base):
    """Virtual money only. `cash` is a cache of the ledger; reconciliation proves they agree."""

    __tablename__ = "portfolios"
    __table_args__ = (
        CheckConstraint("cash >= 0", name="cash_not_negative"),
        CheckConstraint("mode IN ('live_paper', 'backtest')", name="mode_valid"),
    )

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, server_default="live_paper")
    starting_capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = _now()


class Order(Base):
    """Work queue: an approved decision waiting for its first usable price. The only mutable
    trading table besides positions; the outcome lives in the immutable trades table."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="side_valid"),
        CheckConstraint("status IN ('pending', 'filled', 'expired')", name="status_valid"),
        CheckConstraint("reason IN ('signal', 'stop_loss', 'take_profit')", name="reason_valid"),
        Index("ix_orders_pending", "portfolio_id", "status"),
    )

    id: Mapped[uuid.UUID] = _id()
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_decisions.id", ondelete="RESTRICT")
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    reason: Mapped[str] = mapped_column(String(12), nullable=False, server_default="signal")
    notional: Mapped[Decimal | None] = mapped_column(MONEY)  # buys: cash to spend, fee included
    quantity: Mapped[Decimal | None] = mapped_column(QTY)  # sells: units to sell
    stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trade_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()


class RiskDecision(Base):
    """Every signal gets one verdict per portfolio, with every rule that was checked. Immutable."""

    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'reduced', 'rejected')", name="decision_valid"),
        UniqueConstraint("signal_id", "portfolio_id", name="signal_portfolio"),
    )

    id: Mapped[uuid.UUID] = _id()
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    rules_evaluated: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    requested_notional: Mapped[Decimal | None] = mapped_column(MONEY)
    approved_notional: Mapped[Decimal | None] = mapped_column(MONEY)
    portfolio_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _now()


class Trade(Base):
    """A simulated execution. Immutable; corrections are new opposing trades."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="side_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("fee >= 0", name="fee_not_negative"),
        Index("ix_trades_portfolio_seq", "portfolio_id", "seq"),
        Index("ix_trades_asset_executed", "asset_id", "executed_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    reason: Mapped[str] = mapped_column(String(12), nullable=False, server_default="signal")
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # after slippage
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash_change: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # signed, fee included
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    price_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _now()


class CashLedger(Base):
    """Double-entry-lite: every change to cash, with the balance after it. Immutable."""

    __tablename__ = "cash_ledger"
    __table_args__ = (
        CheckConstraint("kind IN ('deposit', 'trade')", name="kind_valid"),
        CheckConstraint("balance_after >= 0", name="balance_not_negative"),
        Index("ix_cash_ledger_portfolio_seq", "portfolio_id", "seq"),
    )

    id: Mapped[uuid.UUID] = _id()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = _now()


class Position(Base):
    """Current holding per asset, derived from trades; reconciliation proves it. Mutable."""

    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity_not_negative"),
        Index(
            "uq_positions_open",
            "portfolio_id",
            "asset_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )  # the signal that opened it
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY)
    target_price: Mapped[Decimal | None] = mapped_column(MONEY)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class PortfolioSnapshot(Base):
    """Portfolio value at a point in time. total_value is null when a price was missing: an
    incomplete valuation is recorded as incomplete, never guessed. Immutable."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("portfolio_id", "as_of", name="portfolio_as_of"),)

    id: Mapped[uuid.UUID] = _id()
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    positions_value: Mapped[Decimal | None] = mapped_column(MONEY)
    total_value: Mapped[Decimal | None] = mapped_column(MONEY)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()
