from datetime import date
from decimal import Decimal
import math

from app.ingest.normalize import normalize_date, normalize_amount, clean_description


def test_normalize_date_formats():
    assert normalize_date("02/04/2026") == date(2026, 4, 2)  # day-first
    assert normalize_date("02-04-2026") == date(2026, 4, 2)
    assert normalize_date("02 Apr 2026") == date(2026, 4, 2)
    assert normalize_date("02-Apr-2026") == date(2026, 4, 2)
    assert normalize_date("2026-04-02") == date(2026, 4, 2)


def test_normalize_date_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        normalize_date("not a date")


def test_normalize_amount_strips_currency_and_commas():
    assert normalize_amount("₹45,000.00") == Decimal("45000.00")
    assert normalize_amount("1,200.50 Cr") == Decimal("1200.50")
    assert normalize_amount("INR 500") == Decimal("500")


def test_normalize_amount_handles_pandas_nan():
    # Regression: empty CSV cells arrive as float('nan'), which used to
    # become Decimal('NaN') (always truthy) instead of None.
    assert normalize_amount(float("nan")) is None


def test_normalize_amount_none_passthrough():
    assert normalize_amount(None) is None


def test_clean_description_collapses_whitespace():
    assert clean_description("  UPI   PAYMENT   ") == "UPI PAYMENT"
