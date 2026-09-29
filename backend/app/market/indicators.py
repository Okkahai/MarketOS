"""Technical indicators as pure functions over price lists.

Indicators are statistics, so they use floats; the result never flows into balances or fills.
Every series function returns a list aligned to its input, with None where there is not enough
history yet. Callers pass only bars that were available at their decision time.
"""

import math
import statistics
from collections.abc import Sequence
from datetime import datetime

Series = list[float | None]


def return_series(closes: Sequence[float], n: int) -> Series:
    """Simple return over n bars: close[i] / close[i-n] - 1."""
    return [closes[i] / closes[i - n] - 1 if i >= n else None for i in range(len(closes))]


def sma_series(values: Sequence[float], n: int) -> Series:
    return [
        math.fsum(values[i - n + 1 : i + 1]) / n if i >= n - 1 else None for i in range(len(values))
    ]


def ema_series(values: Sequence[float | None], n: int) -> Series:
    """EMA with alpha 2/(n+1), seeded with the SMA of the first n available values."""
    out: Series = [None] * len(values)
    alpha = 2 / (n + 1)
    run: list[float] = []
    prev: float | None = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            run.append(v)
            if len(run) == n:
                prev = math.fsum(run) / n
                out[i] = prev
        else:
            prev = alpha * v + (1 - alpha) * prev
            out[i] = prev
    return out


def rsi_series(closes: Sequence[float], n: int = 14) -> Series:
    """Wilder's RSI. Flat prices give 50; all gains give 100."""
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = math.fsum(gains[:n]) / n
    avg_loss = math.fsum(losses[:n]) / n
    out[n] = _rsi(avg_gain, avg_loss)
    for i in range(n, len(deltas)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] = _rsi(avg_gain, avg_loss)
    return out


def _rsi(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def macd_series(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Series, Series, Series]:
    """(macd line, signal line, histogram)."""
    fast_ema, slow_ema = ema_series(closes, fast), ema_series(closes, slow)
    line: Series = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_ema, slow_ema, strict=True)
    ]
    sig = ema_series(line, signal)
    hist: Series = [
        m - s if m is not None and s is not None else None for m, s in zip(line, sig, strict=True)
    ]
    return line, sig, hist


def atr_series(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14
) -> Series:
    """Wilder's ATR. True range starts at the second bar (it needs a previous close)."""
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    tr = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    atr = math.fsum(tr[:n]) / n
    out[n] = atr
    for i in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[i]) / n
        out[i + 1] = atr
    return out


def volatility_series(closes: Sequence[float], n: int = 20) -> Series:
    """Sample standard deviation of the last n one-bar returns (per-bar, not annualised)."""
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    out: Series = [None] * len(closes)
    for i in range(n, len(closes)):
        out[i] = statistics.stdev(rets[i - n : i])
    return out


def volume_ratio_series(volumes: Sequence[float], n: int = 20) -> Series:
    """Volume relative to the average of the previous n bars (the current bar is excluded)."""
    out: Series = [None] * len(volumes)
    for i in range(n, len(volumes)):
        avg = math.fsum(volumes[i - n : i]) / n
        out[i] = volumes[i] / avg if avg > 0 else None
    return out


def drawdown_series(closes: Sequence[float]) -> Series:
    """Distance below the running peak of the given window (0 at a new high, negative below)."""
    out: Series = []
    peak = -math.inf
    for c in closes:
        peak = max(peak, c)
        out.append(c / peak - 1)
    return out


def relative_strength_and_correlation(
    ts: Sequence[datetime],
    closes: Sequence[float],
    bench_closes: dict[datetime, float],
    n: int = 20,
) -> tuple[Series, Series]:
    """Return-difference and rolling correlation versus a benchmark, on timestamps both have.

    Bars the benchmark lacks (e.g. weekends for a stock benchmark) are dropped, not filled.
    """
    idx = [i for i, t in enumerate(ts) if t in bench_closes]
    a = [closes[i] for i in idx]
    b = [bench_closes[ts[i]] for i in idx]
    rel: Series = [None] * len(closes)
    corr: Series = [None] * len(closes)
    ra = [a[j] / a[j - 1] - 1 for j in range(1, len(a))]
    rb = [b[j] / b[j - 1] - 1 for j in range(1, len(b))]
    for j in range(n, len(a)):
        rel[idx[j]] = (a[j] / a[j - n] - 1) - (b[j] / b[j - n] - 1)
        try:
            corr[idx[j]] = statistics.correlation(ra[j - n : j], rb[j - n : j])
        except statistics.StatisticsError:  # constant returns: correlation is undefined
            corr[idx[j]] = None
    return rel, corr


def compute_indicators(
    ts: Sequence[datetime],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    bench_closes: dict[datetime, float] | None = None,
) -> dict[str, Series]:
    macd, macd_signal, macd_hist = macd_series(closes)
    atr = atr_series(highs, lows, closes)
    out: dict[str, Series] = {
        "ret_1": return_series(closes, 1),
        "ret_5": return_series(closes, 5),
        "ret_20": return_series(closes, 20),
        "vol_20": volatility_series(closes, 20),
        "sma_20": sma_series(closes, 20),
        "sma_50": sma_series(closes, 50),
        "sma_200": sma_series(closes, 200),
        "ema_12": ema_series(closes, 12),
        "ema_26": ema_series(closes, 26),
        "rsi_14": rsi_series(closes, 14),
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "atr_14": atr,
        "atr_14_pct": [a / c if a is not None else None for a, c in zip(atr, closes, strict=True)],
        "volume_ratio_20": volume_ratio_series(volumes, 20),
        "drawdown": drawdown_series(closes),
    }
    if bench_closes:
        out["rel_strength_20"], out["corr_20"] = relative_strength_and_correlation(
            ts, closes, bench_closes, 20
        )
    return out
