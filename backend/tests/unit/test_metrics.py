"""Performance maths checked against numbers worked out by hand."""

from math import sqrt

import pytest

from app.analytics import metrics as m


def test_returns_drawdown_and_total():
    assert m.daily_returns([100, 110, 99]) == pytest.approx([0.10, -0.10])
    assert m.total_return_pct([100, 120, 90, 110]) == pytest.approx(10.0)
    assert m.max_drawdown_pct([100, 120, 90, 110]) == pytest.approx(25.0)  # 120 -> 90
    assert m.max_drawdown_pct([100, 110, 120]) == 0.0
    assert m.total_return_pct([100]) is None and m.max_drawdown_pct([]) is None


def test_sharpe_and_sortino_on_a_four_day_series():
    r = [0.02, -0.01, 0.03, 0.0]  # mean 0.01; sample variance 0.001 / 3
    assert m.sharpe(r) == pytest.approx(0.01 / sqrt(0.001 / 3) * sqrt(365))
    assert m.sortino(r) == pytest.approx(0.01 / sqrt(0.0001 / 4) * sqrt(365))  # only -0.01 hurts


def test_ratios_are_none_when_undefined():
    assert m.sharpe([0.01]) is None and m.sortino([0.01]) is None
    assert m.sharpe([0.01, 0.01]) is None  # no variance
    assert m.sortino([0.01, 0.02]) is None  # no losing day


def test_trade_statistics_include_the_losers():
    s = m.trade_stats([100, -50, 50, -25])
    assert (s["closed"], s["wins"], s["losses"], s["win_rate"]) == (4, 2, 2, 0.5)
    assert s["profit_factor"] == 2.0  # 150 won, 75 lost
    assert (s["avg_win"], s["avg_loss"], s["expectancy"]) == (75.0, -37.5, 18.75)
    empty = m.trade_stats([])
    assert empty["closed"] == 0 and empty["win_rate"] is None
    assert m.trade_stats([10])["profit_factor"] is None  # nothing lost


def test_direction_judgement():
    assert m.direction_correct("BUY", 1.0) is True
    assert m.direction_correct("STRONG_BUY", -1.0) is False
    assert m.direction_correct("SELL", -0.5) is True
    assert m.direction_correct("AVOID", 0.0) is False  # flat is not a correct bearish call
    assert m.direction_correct("HOLD", 5.0) is None
