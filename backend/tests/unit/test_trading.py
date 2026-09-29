"""Paper trading maths and risk rules, with numbers small enough to check by hand."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.core.config import Settings
from app.trading.risk import Holding, Pending, PortfolioState, SignalView, evaluate
from app.trading.rules import (
    RiskConfig,
    apply_buy,
    apply_sell,
    buy_quantity,
    fee_for,
    session_open,
    slipped_price,
    stop_fill,
    target_fill,
)

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
CFG = RiskConfig.from_settings(Settings())


# --- accounting -----------------------------------------------------------------------------


def test_slippage_is_adverse_and_fee_has_a_floor():
    assert slipped_price(D(100), "BUY", D(5)) == D("100.05")
    assert slipped_price(D(100), "SELL", D(5)) == D("99.95")
    assert fee_for(D(1000), D(40), D(0)) == D(4)
    assert fee_for(D(1000), D(0), D("1.5")) == D("1.5")  # min_fee wins over 0 bps
    assert fee_for(D(0), D(40), D(1)) == D(0)


def test_buy_quantity_rounds_down_and_never_exceeds_notional():
    assert buy_quantity(D(1000), D("100.05"), D(0), D(0), 6) == D("9.995002")
    qty = buy_quantity(D(1000), D(100), D(40), D(0), 8)  # 1000 / (100 * 1.004)
    assert qty * D(100) + fee_for(qty * D(100), D(40), D(0)) <= D(1000)
    assert buy_quantity(D(5), D(100), D(0), D(10), 6) == 0  # the minimum fee alone eats it


def test_average_cost_with_fees_and_realised_pnl():
    a = apply_buy(D(0), D(0), D(10), D(100), D(4))
    assert (a.quantity, a.cost_basis, a.avg_cost) == (D(10), D(1004), D("100.4"))
    b = apply_buy(a.quantity, a.cost_basis, D(10), D(110), D(4))
    assert (b.quantity, b.cost_basis, b.avg_cost) == (D(20), D(2108), D("105.4"))
    s = apply_sell(b.quantity, b.cost_basis, D(5), D(120), D(3))
    assert s.realized_pnl == D(70)  # 600 - 3 - 5 * 105.4
    assert (s.quantity, s.cost_basis, s.avg_cost) == (D(15), D(1581), D("105.4"))
    closed = apply_sell(s.quantity, s.cost_basis, D(15), D(100), D(0))
    assert closed.quantity == 0 and closed.cost_basis == 0 and closed.realized_pnl == D(-81)
    with pytest.raises(ValueError):
        apply_sell(D(1), D(100), D(2), D(100), D(0))


def test_stop_and_target_fill_prices_including_gaps():
    assert stop_fill(D(100), D(90), D(92)) == D(92)
    assert stop_fill(D(88), D(85), D(92)) == D(88)  # gapped through the stop: fills at the open
    assert stop_fill(D(100), D(95), D(92)) is None
    assert target_fill(D(100), D(112), D(110)) == D(110)
    assert target_fill(D(115), D(120), D(110)) == D(115)  # gapped up: fills at the open
    assert target_fill(D(100), D(105), D(110)) is None


def test_session_open_stock_is_the_new_york_open_crypto_is_the_bar_start():
    day = datetime(2026, 8, 3, tzinfo=UTC)
    assert session_open(day, "stock") == datetime(2026, 8, 3, 13, 30, tzinfo=UTC)  # EDT
    winter = datetime(2026, 1, 5, tzinfo=UTC)
    assert session_open(winter, "stock") == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)  # EST
    assert session_open(day, "crypto") == day


# --- risk rules -----------------------------------------------------------------------------


def state(**kw) -> PortfolioState:
    base = dict(cash=D(10000), equity=D(10000), peak_equity=D(10000), holdings={},
                pending_buys={}, last_trade_at={}, trades_today=0)  # fmt: skip
    return PortfolioState(**{**base, **kw})


def signal(action="BUY", conf="0.70", cls="stock", sector="Technology", **kw) -> SignalView:
    base = dict(action=action, confidence=D(conf), asset_id="A", asset_class=cls, sector=sector,
                reference_price_ts=NOW - timedelta(hours=2), size_pct=None, stop_pct=None,
                take_profit_pct=None)  # fmt: skip
    return SignalView(**{**base, **kw})


def holding(asset="X", value=1000, sector="Technology", cls="stock") -> Holding:
    return Holding(asset, sector, cls, D(1), D(value))


def rejected_by(v, rule):
    assert v.decision == "rejected" and v.side is None
    assert any(r["rule"] == rule and not r["passed"] for r in v.rules), v.rules


def test_default_buy_is_sized_and_gets_a_stop():
    v = evaluate(signal(), state(), CFG, NOW)
    assert (v.decision, v.side, v.notional) == ("approved", "BUY", D(400))  # 4% of 10,000
    assert v.stop_pct == D(8) and v.take_profit_pct is None
    assert {r["rule"] for r in v.rules} >= {"min_confidence", "price_fresh", "max_position"}


def test_confidence_floors_including_strong_buy():
    rejected_by(evaluate(signal(conf="0.59"), state(), CFG, NOW), "min_confidence")
    rejected_by(evaluate(signal("STRONG_BUY", "0.70"), state(), CFG, NOW), "min_confidence")
    assert evaluate(signal("STRONG_BUY", "0.75"), state(), CFG, NOW).side == "BUY"


def test_non_trading_actions_are_recorded_as_rejected():
    for action in ("HOLD", "AVOID"):
        rejected_by(evaluate(signal(action), state(), CFG, NOW), "action_tradable")


def test_stale_price_and_unpriced_portfolio_block_entries():
    old = signal(reference_price_ts=NOW - timedelta(hours=101))
    rejected_by(evaluate(old, state(), CFG, NOW), "price_fresh")
    stale_crypto = signal(cls="crypto", reference_price_ts=NOW - timedelta(hours=37))
    rejected_by(evaluate(stale_crypto, state(), CFG, NOW), "price_fresh")
    rejected_by(evaluate(signal(), state(equity=None), CFG, NOW), "data_complete")


def test_drawdown_breaker_blocks_entries_but_not_exits():
    down = state(equity=D(7900), holdings={"A": holding("A")})
    rejected_by(evaluate(signal(), down, CFG, NOW), "drawdown_breaker")
    assert evaluate(signal("SELL", "0.10"), down, CFG, NOW).side == "SELL"
    assert evaluate(signal(), state(equity=D(8000)), CFG, NOW).side == "BUY"  # exactly at the floor


def test_cooldown_and_daily_cap():
    recent = state(last_trade_at={"A": NOW - timedelta(hours=23)})
    rejected_by(evaluate(signal(), recent, CFG, NOW), "cooldown")
    assert evaluate(signal(), state(last_trade_at={"A": NOW - timedelta(hours=25)}), CFG, NOW).side
    rejected_by(evaluate(signal(), state(trades_today=5), CFG, NOW), "daily_trade_cap")


def test_position_count_limit_counts_pending_new_names():
    full = {f"H{i}": holding(f"H{i}", 100, sector=f"S{i}") for i in range(8)}
    rejected_by(evaluate(signal(), state(holdings=full), CFG, NOW), "max_positions")
    seven = {k: full[k] for k in list(full)[:7]}
    rejected_by(
        evaluate(
            signal(),
            state(holdings=seven, pending_buys={"P": Pending(D(100), "Energy", "stock")}),
            CFG,
            NOW,
        ),
        "max_positions",
    )
    adding = {**full, "A": holding("A", 100, sector="S9")}
    del adding["H0"]
    assert evaluate(signal(), state(holdings=adding), CFG, NOW).side == "BUY"


def test_size_is_capped_then_reduced_by_the_tightest_limit():
    assert evaluate(signal(size_pct=D(15)), state(), CFG, NOW).notional == D(1000)  # 10% cap
    held = state(holdings={"A": holding("A", 800)})
    v = evaluate(signal(), held, CFG, NOW)  # wants 400, only 200 left under 10%
    assert (v.decision, v.notional) == ("reduced", D(200))
    sector = state(holdings={"X": holding("X", 2950)})
    assert evaluate(signal(), sector, CFG, NOW).notional == D(50)  # 30% sector cap
    crypto = state(holdings={"X": holding("X", 2400, sector=None, cls="crypto")})
    v = evaluate(signal(cls="crypto", sector=None), crypto, CFG, NOW)
    assert v.notional == D(100)  # 25% crypto cap


def test_cash_reserve_and_pending_orders_limit_spending():
    v = evaluate(signal(), state(cash=D(1050)), CFG, NOW)  # keeps 10% (1,000) in cash
    assert (v.decision, v.notional) == ("reduced", D(50))
    rejected_by(evaluate(signal(), state(cash=D(1040)), CFG, NOW), "min_trade_size")
    promised = state(cash=D(1500), pending_buys={"Z": Pending(D(450), "Health Care", "stock")})
    assert evaluate(signal(), promised, CFG, NOW).notional == D(50)


def test_pending_buys_count_against_sector_and_crypto_limits():
    tech = state(pending_buys={"Z": Pending(D(2950), "Technology", "stock")})
    assert evaluate(signal(), tech, CFG, NOW).notional == D(50)
    coin = state(pending_buys={"Z": Pending(D(2400), None, "crypto")})
    assert evaluate(signal(cls="crypto", sector=None), coin, CFG, NOW).notional == D(100)


def test_stop_and_take_profit_are_capped():
    v = evaluate(signal(stop_pct=D(15), take_profit_pct=D(50)), state(), CFG, NOW)
    assert (v.stop_pct, v.take_profit_pct) == (D(10), D(30))
    assert evaluate(signal(stop_pct=D(5)), state(), CFG, NOW).stop_pct == D(5)


def test_exits_need_a_position_and_reduce_sells_half():
    rejected_by(evaluate(signal("SELL"), state(), CFG, NOW), "position_held")
    held = state(holdings={"A": holding("A")})
    assert evaluate(signal("SELL"), held, CFG, NOW).fraction == D(1)
    assert evaluate(signal("REDUCE"), held, CFG, NOW).fraction == D("0.5")
