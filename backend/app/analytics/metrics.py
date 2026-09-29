"""Performance maths over stored history. Pure functions, no database.

Ratios are floats (they are statistics, not money). Money totals stay Decimal at the callers.
Annualisation uses 365 days because the book mixes crypto (trades every day) with stocks; the
risk-free rate is taken as 0. Both choices are shown next to the numbers in the API.
"""

from math import sqrt

DAYS_PER_YEAR = 365


def daily_returns(values: list[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(values, values[1:], strict=False) if a > 0]


def total_return_pct(values: list[float]) -> float | None:
    if len(values) < 2 or values[0] <= 0:
        return None
    return (values[-1] / values[0] - 1) * 100


def max_drawdown_pct(values: list[float]) -> float | None:
    """Largest fall from a running peak, as a positive percentage."""
    if not values:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst * 100


def sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return None if var == 0 else mean / sqrt(var) * sqrt(DAYS_PER_YEAR)


def sortino(returns: list[float]) -> float | None:
    """Mean over downside deviation (target 0); None if there was no down day."""
    if len(returns) < 2:
        return None
    dd = sqrt(sum(min(r, 0.0) ** 2 for r in returns) / len(returns))
    return None if dd == 0 else sum(returns) / len(returns) / dd * sqrt(DAYS_PER_YEAR)


def trade_stats(pnls: list[float]) -> dict[str, float | int | None]:
    """Per closed position. profit_factor is None when nothing was lost."""
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    n = len(pnls)
    return {
        "closed": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n if n else None,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "avg_win": gross_win / len(wins) if wins else None,
        "avg_loss": -gross_loss / len(losses) if losses else None,
        "expectancy": sum(pnls) / n if n else None,
    }


def direction_correct(action: str, return_pct: float) -> bool | None:
    """Bullish actions are right when the price rose, bearish ones when it fell; HOLD makes no
    directional claim. A flat result counts as wrong for a directional call."""
    if action in ("STRONG_BUY", "BUY"):
        return return_pct > 0
    if action in ("SELL", "REDUCE", "AVOID"):
        return return_pct < 0
    return None
