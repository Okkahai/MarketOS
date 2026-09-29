"""The only place cash and positions change. One transaction: trade + ledger row + position +
portfolio cash + order, so a crash can never leave half a trade."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import quantize_money, quantize_quantity
from app.models import Asset, CashLedger, Order, Portfolio, Position, Trade
from app.trading.rules import (
    QUANTITY_PLACES,
    RiskConfig,
    apply_buy,
    apply_sell,
    buy_quantity,
    fee_for,
    slipped_price,
    stop_price,
    target_price,
)

ZERO = Decimal(0)


def execute_order(
    session: Session,
    order: Order,
    asset: Asset,
    cfg: RiskConfig,
    reference_price: Decimal,
    price_ts: datetime,
    executed_at: datetime,
) -> Trade | None:
    """Fill a pending order at reference_price (plus adverse slippage). Returns the trade, or None
    when it cannot be filled (no cash, no position, quantity rounds to zero): the order expires."""
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.id == order.portfolio_id).with_for_update()
    ).scalar_one()
    position = session.scalar(
        select(Position).where(
            Position.portfolio_id == portfolio.id,
            Position.asset_id == asset.id,
            Position.closed_at.is_(None),
        )
    )
    places = QUANTITY_PLACES[asset.asset_class]
    bps = cfg.slippage_bps(asset.asset_class)
    fee_bps = cfg.fee_bps(asset.asset_class)
    price = slipped_price(reference_price, order.side, bps)

    if order.side == "BUY":
        assert order.notional is not None
        qty = buy_quantity(min(order.notional, portfolio.cash), price, fee_bps, cfg.min_fee, places)
    else:
        qty = ZERO if position is None else min(order.quantity or ZERO, position.quantity)
        qty = quantize_quantity(qty, places)
    if qty <= 0:
        order.status = "expired"
        session.commit()
        return None

    gross = quantize_money(qty * price)
    fee = fee_for(gross, fee_bps, cfg.min_fee)
    cash_change = -(gross + fee) if order.side == "BUY" else gross - fee
    if portfolio.cash + cash_change < 0:
        order.status = "expired"
        session.commit()
        return None

    old_qty = position.quantity if position else ZERO
    old_basis = position.cost_basis if position else ZERO
    if order.side == "BUY":
        after = apply_buy(old_qty, old_basis, qty, price, fee)
    else:
        after = apply_sell(old_qty, old_basis, qty, price, fee)

    trade = Trade(
        portfolio_id=portfolio.id, asset_id=asset.id, signal_id=order.signal_id,
        order_id=order.id, side=order.side, reason=order.reason, quantity=qty,
        reference_price=reference_price, price=price, slippage_bps=bps, fee=fee,
        cash_change=cash_change, realized_pnl=after.realized_pnl, price_ts=price_ts,
        executed_at=executed_at,
    )  # fmt: skip
    session.add(trade)
    session.flush()

    portfolio.cash = portfolio.cash + cash_change
    session.add(
        CashLedger(
            portfolio_id=portfolio.id,
            kind="trade",
            amount=cash_change,
            balance_after=portfolio.cash,
            trade_id=trade.id,
        )  # fmt: skip
    )
    if position is None:
        position = Position(
            portfolio_id=portfolio.id, asset_id=asset.id, signal_id=order.signal_id,
            quantity=ZERO, avg_cost=ZERO, cost_basis=ZERO, realized_pnl=ZERO, opened_at=executed_at,
            last_entry_at=executed_at,
        )  # fmt: skip
        session.add(position)
    position.quantity, position.avg_cost = after.quantity, after.avg_cost
    position.cost_basis = after.cost_basis
    position.realized_pnl = position.realized_pnl + after.realized_pnl
    if order.side == "BUY":
        position.last_entry_at = executed_at
        if order.stop_loss_pct is not None:
            position.stop_price = stop_price(after.avg_cost, order.stop_loss_pct)
        if order.take_profit_pct is not None:
            position.target_price = target_price(after.avg_cost, order.take_profit_pct)
    elif after.quantity == 0:
        position.closed_at = executed_at
    order.status, order.filled_at, order.trade_id = "filled", executed_at, trade.id
    session.commit()
    return trade
