"""Money helpers.

Every amount in the program is an integer number of euro cents. Integers add up
exactly, so totals over thousands of simulated product-days never drift the way
floats do (0.1 + 0.2 == 0.30000000000000004). We convert to cents once, when
reading input, and back to euros only when writing output.
"""


def to_cents(value: str | int | float) -> int:
    """Convert a euro amount such as "1.20" or 0.02 into integer cents.

    The amount is read as text and split at the decimal point, so no float
    arithmetic is involved: "0.07" becomes 0 euros and 7 cents.
    Raises ValueError if the value is not a number or has more than two decimals.
    """
    text = str(value).strip()
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]

    if "." in text:
        euros, decimals = text.split(".", 1)
    else:
        euros, decimals = text, ""

    # Both parts may only contain digits, and at least one must be non-empty.
    if (euros and not euros.isdigit()) or (decimals and not decimals.isdigit()) \
            or (not euros and not decimals):
        raise ValueError(f"must be a number, got {value!r}")
    if len(decimals) > 2:
        raise ValueError(f"must have at most two decimal places, got {value!r}")

    decimals = decimals.ljust(2, "0")  # "5" -> "50", "" -> "00"
    return sign * (int(euros or "0") * 100 + int(decimals))


def format_eur(cents: int) -> str:
    """Format cents as a plain euro amount: 123456 -> "1234.56", -5 -> "-0.05"."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros}.{rest:02d}"
