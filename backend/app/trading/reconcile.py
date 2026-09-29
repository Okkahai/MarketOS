"""Reconciliation: rebuild cash and positions from the immutable trades and check they agree
with the stored state. Any disagreement is reported, never silently corrected."""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, LiveClock
from app.jobs.runner import run_job
from app.models import CashLedger, Portfolio, Position, Trade
from app.trading.rules import apply_buy, apply_sell

ZERO = Decimal(0)


def reconcile(session: Session, portfolio: Portfolio) -> list[str]:
    issues: list[str] = []
    ledger = session.scalars(
        select(CashLedger).where(CashLedger.portfolio_id == portfolio.id).order_by(CashLedger.seq)
    ).all()
    trades = session.scalars(
        select(Trade).where(Trade.portfolio_id == portfolio.id).order_by(Trade.seq)
    ).all()

    balance = ZERO
    for row in ledger:
        balance += row.amount
        if balance != row.balance_after:
            issues.append(f"ledger seq {row.seq}: balance {row.balance_after}, replay {balance}")
    if balance != portfolio.cash:
        issues.append(f"portfolio cash {portfolio.cash} != ledger sum {balance}")
    by_trade = defaultdict(list)
    for row in ledger:
        if row.trade_id:
            by_trade[row.trade_id].append(row.amount)
    for tr in trades:
        gross = tr.quantity * tr.price
        expected = -(gross + tr.fee) if tr.side == "BUY" else gross - tr.fee
        if abs(tr.cash_change - expected) > Decimal("0.00000001"):
            issues.append(f"trade {tr.id}: cash_change {tr.cash_change}, recomputed {expected}")
        if by_trade.get(tr.id) != [tr.cash_change]:
            issues.append(
                f"trade {tr.id}: ledger rows {by_trade.get(tr.id)} != one {tr.cash_change}"
            )

    qty: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    basis: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    realized: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for tr in trades:
        a = tr.asset_id
        try:
            if tr.side == "BUY":
                after = apply_buy(qty[a], basis[a], tr.quantity, tr.price, tr.fee)
            else:
                after = apply_sell(qty[a], basis[a], tr.quantity, tr.price, tr.fee)
        except ValueError as exc:
            issues.append(f"trade {tr.id}: {exc}")
            continue
        qty[a], basis[a] = after.quantity, after.cost_basis
        realized[a] += after.realized_pnl
        if after.realized_pnl != tr.realized_pnl:
            issues.append(f"trade {tr.id}: realized {tr.realized_pnl}, replay {after.realized_pnl}")

    stored_qty: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    stored_basis: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    stored_real: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for pos in session.scalars(select(Position).where(Position.portfolio_id == portfolio.id)):
        stored_qty[pos.asset_id] += pos.quantity
        stored_basis[pos.asset_id] += pos.cost_basis
        stored_real[pos.asset_id] += pos.realized_pnl
    for a in set(qty) | set(stored_qty):
        if (qty[a], basis[a], realized[a]) != (stored_qty[a], stored_basis[a], stored_real[a]):
            issues.append(
                f"asset {a}: positions hold {stored_qty[a]}/{stored_basis[a]}/{stored_real[a]}, "
                f"trades replay to {qty[a]}/{basis[a]}/{realized[a]}"
            )
    return issues


def run_reconcile(
    session_factory: sessionmaker[Session], *, clock: Clock | None = None
) -> uuid.UUID:
    with run_job(session_factory, "reconcile", clock=clock or LiveClock()) as ctx:
        with session_factory() as session:
            problems: dict[str, list[str]] = {}
            for p in session.scalars(select(Portfolio)):
                issues = reconcile(session, p)
                if issues:
                    problems[p.name] = issues
        ctx.details = {"issues": problems}
        if problems:
            ctx.status = "failed"  # visible on the monitoring page; nothing was changed
        return ctx.run_id
