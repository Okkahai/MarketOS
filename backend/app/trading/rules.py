"""Paper trading rules as data, plus the pure accounting maths.

Everything here is Decimal and has no database access, so each formula can be checked by hand.
Simulation only: nothing in this package talks to a broker or the network.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.money import quantize_money, quantize_quantity

BPS = Decimal(10_000)
NEW_YORK = ZoneInfo("America/New_York")
STOCK_OPEN = time(9, 30)
QUANTITY_PLACES = {"stock": 6, "etf": 6, "crypto": 8}
ENGINE_VERSION = "risk-1"


@dataclass(frozen=True, slots=True)
class RiskConfig:
    min_confidence: Decimal
    strong_buy_min_confidence: Decimal
    max_position_pct: Decimal
    max_sector_pct: Decimal
    max_crypto_pct: Decimal
    min_cash_pct: Decimal
    max_open_positions: int
    min_trade_usd: Decimal
    default_position_pct: Decimal
    cooldown_hours: int
    max_trades_per_day: int
    default_stop_pct: Decimal
    max_stop_pct: Decimal
    max_take_profit_pct: Decimal
    drawdown_breaker_pct: Decimal
    order_expiry_hours: int
    max_price_age_hours_stock: int
    max_price_age_hours_crypto: int
    slippage_bps_stock: Decimal
    slippage_bps_crypto: Decimal
    fee_bps_stock: Decimal
    fee_bps_crypto: Decimal
    min_fee: Decimal
    crypto_fill_interval: str

    @classmethod
    def from_settings(cls, s: Settings) -> "RiskConfig":
        return cls(**{f: getattr(s, f"paper_{f}") for f in cls.__dataclass_fields__})

    def snapshot(self) -> dict[str, str | int]:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(self).items()}

    def slippage_bps(self, asset_class: str) -> Decimal:
        return self.slippage_bps_crypto if asset_class == "crypto" else self.slippage_bps_stock

    def fee_bps(self, asset_class: str) -> Decimal:
        return self.fee_bps_crypto if asset_class == "crypto" else self.fee_bps_stock

    def max_price_age_hours(self, asset_class: str) -> int:
        if asset_class == "crypto":
            return self.max_price_age_hours_crypto
        return self.max_price_age_hours_stock


def fill_interval(config: RiskConfig, asset_class: str) -> str:
    return config.crypto_fill_interval if asset_class == "crypto" else "1d"


def session_open(bar_ts: datetime, asset_class: str) -> datetime:
    """When the price a bar's open refers to was set. A stock's daily bar is dated by its trading
    day (midnight UTC); its open is the 09:30 New York opening auction. Crypto bars open at ts."""
    if asset_class == "crypto":
        return bar_ts
    day = date(bar_ts.year, bar_ts.month, bar_ts.day)
    return datetime.combine(day, STOCK_OPEN, tzinfo=NEW_YORK).astimezone(UTC)


def slipped_price(reference: Decimal, side: str, bps: Decimal) -> Decimal:
    """Adverse slippage: buys pay more, sells receive less."""
    factor = Decimal(1) + bps / BPS if side == "BUY" else Decimal(1) - bps / BPS
    return quantize_money(reference * factor)


def fee_for(gross: Decimal, fee_bps: Decimal, min_fee: Decimal) -> Decimal:
    """max(min_fee, gross * bps / 10,000). A zero-gross trade costs nothing."""
    if gross <= 0:
        return Decimal(0)
    return quantize_money(max(min_fee, gross * fee_bps / BPS))


def buy_quantity(
    notional: Decimal, execution_price: Decimal, fee_bps: Decimal, min_fee: Decimal, places: int
) -> Decimal:
    """Largest quantity (rounded down) whose cost plus fee stays within the notional."""
    qty = quantize_quantity(notional / (execution_price * (Decimal(1) + fee_bps / BPS)), places)
    step = Decimal(1).scaleb(-places)
    while (
        qty > 0
        and qty * execution_price + fee_for(qty * execution_price, fee_bps, min_fee) > notional
    ):
        qty -= step  # a minimum fee can push the total over; give back one step
    return max(qty, Decimal(0))


@dataclass(frozen=True, slots=True)
class PositionAfter:
    quantity: Decimal
    avg_cost: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal  # this trade's realised P&L (0 for a buy)


def apply_buy(
    old_qty: Decimal, old_basis: Decimal, qty: Decimal, price: Decimal, fee: Decimal
) -> PositionAfter:
    """Average cost with buy fees capitalised: new_avg = (old_basis + qty*price + fee) / new_qty."""
    new_qty = old_qty + qty
    basis = quantize_money(old_basis + qty * price + fee)
    return PositionAfter(new_qty, _avg(basis, new_qty), basis, Decimal(0))


def apply_sell(
    old_qty: Decimal, old_basis: Decimal, qty: Decimal, price: Decimal, fee: Decimal
) -> PositionAfter:
    """realised = qty*price - fee - qty*avg_cost; average cost is unchanged by a sell."""
    if qty > old_qty:
        raise ValueError("cannot sell more than the position holds")
    avg = _avg(old_basis, old_qty)
    new_qty = old_qty - qty
    basis = Decimal(0) if new_qty == 0 else quantize_money(new_qty * avg)
    realized = quantize_money(qty * price - fee - qty * avg)
    return PositionAfter(new_qty, avg if new_qty else Decimal(0), basis, realized)


def _avg(basis: Decimal, qty: Decimal) -> Decimal:
    return (basis / qty).quantize(Decimal("1e-10"), rounding=ROUND_HALF_EVEN) if qty else Decimal(0)


def stop_price(avg_cost: Decimal, pct: Decimal) -> Decimal:
    return quantize_money(avg_cost * (Decimal(1) - pct / 100))


def target_price(avg_cost: Decimal, pct: Decimal) -> Decimal:
    return quantize_money(avg_cost * (Decimal(1) + pct / 100))


def stop_fill(bar_open: Decimal, bar_low: Decimal, stop: Decimal) -> Decimal | None:
    """Reference price for a stop-loss, or None if the bar never reached it. A gap through the
    stop fills at the open, which is worse than the stop."""
    if bar_low > stop:
        return None
    return min(stop, bar_open)


def target_fill(bar_open: Decimal, bar_high: Decimal, target: Decimal) -> Decimal | None:
    """Reference price for a take-profit, or None. The order rests at the target and fills at the
    open only when the bar gapped past it."""
    if bar_high < target:
        return None
    return max(target, bar_open)
