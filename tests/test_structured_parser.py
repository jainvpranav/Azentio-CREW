import os
import tempfile
from decimal import Decimal

from app.ingest.structured_parser import find_columns, parse_csv
import pandas as pd


def test_find_columns_matches_withdrawal_deposit_headers():
    # Regression: fuzzy-matching the HEADER NAME against the bare field name
    # ("debit" vs "Withdrawal") used to fail since the strings don't look
    # alike, silently dropping every transaction.
    df = pd.DataFrame(columns=["Date", "Narration", "Withdrawal", "Deposit", "Balance"])
    columns = find_columns(df)
    assert columns["debit"] == "Withdrawal"
    assert columns["credit"] == "Deposit"
    assert columns["date"] == "Date"
    assert columns["description"] == "Narration"


def test_find_columns_does_not_mismatch_description_as_credit():
    # Regression: "Description" contains the substring "cr" (de-s-cr-iption),
    # which used to beat the real "Credit" column for the weak 'cr' keyword
    # since credit_candidates picked the first column-order match.
    df = pd.DataFrame(columns=["Date", "Description", "Debit", "Credit", "Balance"])
    columns = find_columns(df)
    assert columns["credit"] == "Credit"
    assert columns["debit"] == "Debit"
    assert columns["description"] == "Description"


def test_find_columns_falls_back_to_position_for_description():
    df = pd.DataFrame(columns=["Transaction Date", "Merchant", "Amount Debited", "Amount Credited"])
    columns = find_columns(df)
    assert columns["description"] == "Merchant"
    assert columns["debit"] == "Amount Debited"
    assert columns["credit"] == "Amount Credited"


def test_parse_csv_infers_opening_closing_from_balance_column():
    content = (
        "Date,Narration,Withdrawal,Deposit,Balance\n"
        "01/04/2026,SALARY,,45000.00,95000.00\n"
        "02/04/2026,RENT,5000.00,,90000.00\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        f.write(content)
        path = f.name

    try:
        statement = parse_csv(path)
        assert len(statement.transactions) == 2
        assert statement.opening_balance == Decimal("50000.00")
        assert statement.closing_balance == Decimal("90000.00")
    finally:
        os.unlink(path)


def test_parse_csv_skips_rows_with_no_amount():
    content = (
        "Date,Narration,Withdrawal,Deposit,Balance\n"
        "01/04/2026,OPENING BALANCE,,,50000.00\n"
        "02/04/2026,SALARY,,45000.00,95000.00\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        f.write(content)
        path = f.name

    try:
        statement = parse_csv(path)
        assert len(statement.transactions) == 1
        assert statement.transactions[0].description == "SALARY"
    finally:
        os.unlink(path)
