import math
from datetime import UTC, datetime, timedelta

import pytest

from app.market import indicators as ind

# StockCharts' published RSI(14) worked example (Wilder smoothing), full-precision closes.
STOCKCHARTS_CLOSES = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826,
    45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439,
    46.2122, 46.2521, 45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672,
    43.4205, 42.6628, 43.1314,
]  # fmt: skip


def test_rsi_matches_published_worked_example():
    rsi = ind.rsi_series(STOCKCHARTS_CLOSES, 14)
    assert rsi[:14] == [None] * 14
    published = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38]
    assert [round(v, 2) for v in rsi[14:24]] == published


def test_rsi_edge_cases():
    rising = [float(i) for i in range(1, 30)]
    assert ind.rsi_series(rising, 14)[-1] == 100.0
    assert ind.rsi_series([5.0] * 30, 14)[-1] == 50.0
    assert ind.rsi_series([1.0, 2.0], 14) == [None, None]


def test_sma_and_returns():
    assert ind.sma_series([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    assert ind.return_series([100.0, 110.0, 99.0], 1) == [
        None,
        pytest.approx(0.1),
        pytest.approx(-0.1),
    ]
    assert ind.return_series([100.0, 110.0], 5) == [None, None]


def test_ema_is_seeded_with_sma_then_recursive():
    out = ind.ema_series([1.0, 2.0, 3.0, 4.0], 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0  # SMA of the first three
    assert out[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)  # alpha = 2/(3+1)


def test_macd_of_a_straight_line_is_exactly_the_ema_lag_difference():
    # For close_t = t an EMA(n) lags by (n-1)/2, so MACD(12,26) = 12.5 - 5.5 = 7 exactly.
    closes = [float(t) for t in range(1, 80)]
    line, signal, hist = ind.macd_series(closes)
    assert line[24] is None and line[25] == pytest.approx(7.0)
    assert signal[32] is None and signal[33] == pytest.approx(7.0)
    assert hist[-1] == pytest.approx(0.0, abs=1e-9)


def test_atr_constant_range_and_gap():
    n = 20
    highs, lows, closes = [11.0] * n, [9.0] * n, [10.0] * n
    assert ind.atr_series(highs, lows, closes, 14)[14] == pytest.approx(2.0)
    # A gap up: the true range includes the jump from the previous close.
    assert ind.atr_series([11, 21], [9, 19], [10, 20], 1)[1] == pytest.approx(11.0)


def test_volatility_is_zero_for_constant_growth_and_positive_otherwise():
    steady = [100 * 1.01**i for i in range(30)]
    assert ind.volatility_series(steady, 20)[-1] == pytest.approx(0.0, abs=1e-12)
    zigzag = [100.0, 102.0] * 15
    assert ind.volatility_series(zigzag, 20)[-1] > 0.01


def test_volume_ratio_excludes_the_current_bar():
    volumes = [100.0] * 20 + [300.0]
    assert ind.volume_ratio_series(volumes, 20)[-1] == pytest.approx(3.0)
    assert ind.volume_ratio_series([0.0] * 21, 20)[-1] is None


def test_drawdown():
    out = ind.drawdown_series([100.0, 120.0, 90.0, 130.0])
    assert out == [0.0, 0.0, pytest.approx(-0.25), 0.0]


def _days(n: int) -> list[datetime]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [start + timedelta(days=i) for i in range(n)]


def test_relative_strength_and_correlation_versus_benchmark():
    ts = _days(30)
    bench = [100 * 1.001**i * (1 + 0.01 * (i % 2)) for i in range(30)]
    asset = [c * 2 for c in bench]  # same returns, different level
    rel, corr = ind.relative_strength_and_correlation(
        ts, asset, dict(zip(ts, bench, strict=True)), 20
    )
    assert rel[19] is None and corr[19] is None
    assert rel[-1] == pytest.approx(0.0, abs=1e-12)
    assert corr[-1] == pytest.approx(1.0)
    inverse = [10000 / c for c in bench]
    _, corr_inv = ind.relative_strength_and_correlation(
        ts, inverse, dict(zip(ts, bench, strict=True)), 20
    )
    assert corr_inv[-1] < -0.9


def test_benchmark_alignment_drops_missing_timestamps_instead_of_filling():
    ts = _days(30)
    closes = [100.0 + i for i in range(30)]
    bench_days = {t: 50.0 + i for i, t in enumerate(ts) if i % 7 not in (5, 6)}  # no weekends
    rel, _ = ind.relative_strength_and_correlation(ts, closes, bench_days, 5)
    weekend = [i for i in range(30) if i % 7 in (5, 6)]
    assert all(rel[i] is None for i in weekend)
    assert any(v is not None for v in rel)


def test_compute_indicators_returns_aligned_named_series():
    n = 60
    ts = _days(n)
    closes = [100 + math.sin(i / 3) * 5 for i in range(n)]
    out = ind.compute_indicators(
        ts, [c + 1 for c in closes], [c - 1 for c in closes], closes, [1000.0] * n, None
    )
    assert all(len(v) == n for v in out.values())
    assert {"rsi_14", "macd_hist", "atr_14_pct", "sma_50", "drawdown"} <= out.keys()
    assert "rel_strength_20" not in out
    assert out["sma_50"][48] is None and out["sma_50"][49] is not None
    with_bench = ind.compute_indicators(
        ts, closes, closes, closes, [1.0] * n, dict(zip(ts, closes, strict=True))
    )
    assert "rel_strength_20" in with_bench and "corr_20" in with_bench
