"""Risk engine: turns a signal plus the portfolio's state into one verdict. Pure, no database.

Every rule is recorded with its outcome (rules_evaluated) so a rejection can be read back.
Order: filters that reject outright, then sizing limits (the smallest wins), then exits.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.core.money import quantize_money
from app.trading.rules import RiskConfig

ENTRY = ("STRONG_BUY", "BUY")
EXIT_FRACTION = {"SELL": Decimal(1), "REDUCE": Decimal("0.5")}
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Holding:
    asset_id: str
    sector: str | None
    asset_class: str
    quantity: Decimal
    value: Decimal  # at the latest usable close


@dataclass(frozen=True, slots=True)
class Pending:
    """A buy order approved but not yet filled. It already counts against cash and limits."""

    notional: Decimal
    sector: str | None
    asset_class: str


@dataclass(frozen=True, slots=True)
class PortfolioState:
    cash: Decimal
    equity: Decimal | None  # None: a position could not be priced
    peak_equity: Decimal
    holdings: dict[str, Holding]  # by asset_id
    pending_buys: dict[str, Pending]  # by asset_id
    last_trade_at: dict[str, datetime]  # asset_id -> latest trade
    trades_today: int

    def summary(self) -> dict[str, Any]:
        return {
            "cash": str(self.cash),
            "equity": None if self.equity is None else str(self.equity),
            "peak_equity": str(self.peak_equity),
            "open_positions": len(self.holdings),
            "pending_buy_notional": str(
                sum((p.notional for p in self.pending_buys.values()), ZERO)
            ),
            "trades_today": self.trades_today,
        }


@dataclass(frozen=True, slots=True)
class SignalView:
    action: str
    confidence: Decimal
    asset_id: str
    asset_class: str
    sector: str | None
    reference_price_ts: datetime
    size_pct: Decimal | None
    stop_pct: Decimal | None
    take_profit_pct: Decimal | None


@dataclass(slots=True)
class Verdict:
    decision: str = "rejected"  # approved | reduced | rejected
    side: str | None = None
    notional: Decimal | None = None  # buys
    fraction: Decimal | None = None  # sells: share of the position
    stop_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None
    reasons: list[str] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    requested: Decimal | None = None


def evaluate(sig: SignalView, state: PortfolioState, cfg: RiskConfig, now: datetime) -> Verdict:
    v = Verdict()

    def check(rule: str, ok: bool, detail: str) -> bool:
        v.rules.append({"rule": rule, "passed": ok, "detail": detail})
        if not ok:
            v.reasons.append(f"{rule}: {detail}")
        return ok

    held = state.holdings.get(sig.asset_id)
    if sig.action in EXIT_FRACTION:
        if not check("position_held", held is not None, f"{sig.action} needs an open position"):
            return v
        v.side, v.fraction, v.decision = "SELL", EXIT_FRACTION[sig.action], "approved"
        return v  # exits are never blocked by confidence, cooldown or the drawdown breaker
    if sig.action not in ENTRY:
        check("action_tradable", False, f"{sig.action} does not open or close a position")
        return v
    check("action_tradable", True, sig.action)

    floor = cfg.strong_buy_min_confidence if sig.action == "STRONG_BUY" else cfg.min_confidence
    ok = check("min_confidence", sig.confidence >= floor, f"{sig.confidence} vs {floor}")
    max_age = timedelta(hours=cfg.max_price_age_hours(sig.asset_class))
    age = now - sig.reference_price_ts
    ok &= check("price_fresh", age <= max_age, f"reference price {age} old, limit {max_age}")
    equity = state.equity
    ok &= check("data_complete", equity is not None, "portfolio could be valued")
    if equity is not None:
        floor_eq = state.peak_equity * (1 - cfg.drawdown_breaker_pct / 100)
        ok &= check("drawdown_breaker", equity >= floor_eq, f"equity {equity} vs floor {floor_eq}")
    last = state.last_trade_at.get(sig.asset_id)
    cool = timedelta(hours=cfg.cooldown_hours)
    ok &= check("cooldown", last is None or now - last >= cool, f"last trade {last}, {cool}")
    ok &= check(
        "daily_trade_cap",
        state.trades_today < cfg.max_trades_per_day,
        f"{state.trades_today} of {cfg.max_trades_per_day} today",
    )
    slots = len(state.holdings) + sum(1 for a in state.pending_buys if a not in state.holdings)
    ok &= check(
        "max_positions",
        held is not None or sig.asset_id in state.pending_buys or slots < cfg.max_open_positions,
        f"{slots} of {cfg.max_open_positions} slots used",
    )
    if not ok or equity is None:
        return v

    # Exits attached to the entry: stop required, both capped.
    stop = min(sig.stop_pct or cfg.default_stop_pct, cfg.max_stop_pct)
    take = min(sig.take_profit_pct, cfg.max_take_profit_pct) if sig.take_profit_pct else None
    v.stop_pct, v.take_profit_pct = stop, take
    check("stop_loss_set", True, f"stop {stop}%, take profit {take}%")

    pct = min(sig.size_pct or cfg.default_position_pct, cfg.max_position_pct)
    requested = quantize_money(equity * pct / 100)
    pending = state.pending_buys
    promised = sum((p.notional for p in pending.values()), ZERO)
    sector_used = sum(
        (h.value for h in state.holdings.values() if sig.sector and h.sector == sig.sector), ZERO
    ) + sum((p.notional for p in pending.values() if sig.sector and p.sector == sig.sector), ZERO)
    crypto_used = sum(
        (h.value for h in state.holdings.values() if h.asset_class == "crypto"), ZERO
    ) + sum((p.notional for p in pending.values() if p.asset_class == "crypto"), ZERO)
    room = {
        "max_position": equity * cfg.max_position_pct / 100
        - (held.value if held else ZERO)
        - (pending[sig.asset_id].notional if sig.asset_id in pending else ZERO),
        "cash_reserve": state.cash - promised - equity * cfg.min_cash_pct / 100,
    }
    if sig.sector:
        room["max_sector"] = equity * cfg.max_sector_pct / 100 - sector_used
    if sig.asset_class == "crypto":
        room["max_crypto"] = equity * cfg.max_crypto_pct / 100 - crypto_used
    notional = requested
    for name, headroom in room.items():
        capped = min(notional, max(headroom, ZERO))
        check(name, headroom >= requested, f"room {quantize_money(headroom)} for {requested}")
        notional = capped
    notional = quantize_money(notional)
    v.requested = requested
    if not check(
        "min_trade_size", notional >= cfg.min_trade_usd, f"{notional} vs {cfg.min_trade_usd}"
    ):
        return v
    v.side, v.notional = "BUY", notional
    v.decision = "approved" if notional == requested else "reduced"
    if v.decision == "reduced":
        v.reasons.append(f"sized down from {requested} to {notional}")
    return v
