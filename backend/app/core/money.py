"""Decimal helpers. Money never passes through float."""

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation

MONEY_PLACES = Decimal("0.00000001")  # matches NUMERIC(24, 8)


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("floats are not accepted for money; pass a str or Decimal")
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a decimal number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return result


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_EVEN)


def quantize_quantity(value: Decimal, places: int) -> Decimal:
    """Round a trade quantity down, so a sized order never exceeds its budget."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
