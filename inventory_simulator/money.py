"""Money helpers.

Every amount in the program is an integer number of euro cents. Integers add up
exactly, so totals over thousands of simulated product-days never drift the way
floats do (0.1 + 0.2 == 0.30000000000000004). We convert to cents once, when
reading input, and back to euros only when writing output.
"""

from decimal import Decimal, InvalidOperation


def to_cents(value: str | int | float) -> int:
    """Convert a euro amount such as "1.20" or 0.02 into integer cents.

    Raises ValueError if the value is not a number or has more than two decimals.
    """
    try:
        # Going through str() means the float 0.07 becomes Decimal("0.07")
        # instead of 0.07000000000000000666...
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"must be a number, got {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"must be a finite number, got {value!r}")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"must have at most two decimal places, got {value!r}")
    return int(cents)


def format_eur(cents: int) -> str:
    """Format cents as a plain euro amount: 123456 -> "1234.56", -5 -> "-0.05"."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros}.{rest:02d}"
