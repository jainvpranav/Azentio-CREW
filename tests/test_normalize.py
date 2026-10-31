from datetime import date
from decimal import Decimal
import math

from app.ingest.normalize import normalize_date, normalize_amount, clean_description, extract_transaction_metadata


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


def test_extract_metadata_prose_style_counterparty():
    meta = extract_transaction_metadata("UPI CR FROM BRIGHT RETAIL")
    assert meta["transaction_type"] == "UPI"
    assert meta["counterparty"] == "BRIGHT RETAIL"


def test_extract_metadata_same_counterparty_across_rails():
    # Same real counterparty, different payment rail wording - must extract
    # the same counterparty string so recurrence-based rules group them.
    a = extract_transaction_metadata("UPI CR FROM ZEN ENTERPRISES")
    b = extract_transaction_metadata("NEFT CR FROM ZEN ENTERPRISES")
    assert a["counterparty"] == b["counterparty"] == "ZEN ENTERPRISES"


def test_extract_metadata_slash_delimited_style():
    meta = extract_transaction_metadata("UPI/P2A/412233445566/JOHN DOE/HDFC")
    assert meta["transaction_type"] == "UPI"
    assert meta["reference_number"] == "412233445566"
    assert meta["counterparty"] == "JOHN DOE"


def test_extract_metadata_no_shape_leaves_counterparty_none():
    meta = extract_transaction_metadata("RANDOM SHOP PURCHASE")
    assert meta["counterparty"] is None
    assert meta["transaction_type"] is None
