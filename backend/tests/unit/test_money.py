from decimal import Decimal

import pytest

from app.core.money import quantize_money, quantize_quantity, to_decimal


def test_float_is_refused():
    with pytest.raises(TypeError):
        to_decimal(0.1)


def test_bool_is_refused():
    with pytest.raises(TypeError):
        to_decimal(True)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "", "1,000"])
def test_non_finite_or_malformed_is_refused(bad):
    with pytest.raises(ValueError):
        to_decimal(bad)


def test_decimal_sum_is_exact_where_float_is_not():
    assert to_decimal("0.1") + to_decimal("0.2") == Decimal("0.3")
    assert 0.1 + 0.2 != 0.3


def test_money_rounds_half_even_to_8_places():
    assert quantize_money(Decimal("1.000000005")) == Decimal("1.00000000")
    assert quantize_money(Decimal("1.000000015")) == Decimal("1.00000002")


def test_quantity_always_rounds_down():
    # 400 USD budget at 185.2 per share: rounding up would overspend.
    qty = quantize_quantity(Decimal("400") / Decimal("185.2"), 6)
    assert qty == Decimal("2.159827")
    assert qty * Decimal("185.2") <= Decimal("400")
