"""CSV, Excel, and JSON statement parser using pandas"""
import json
import re
import pandas as pd
from decimal import Decimal
from datetime import date
from typing import Optional, List
from app.ingest.normalize import (
    normalize_date, normalize_amount, clean_description,
    extract_currency_from_amount, KNOWN_ISO_CURRENCIES,
)
from app.ingest.pdf_parser import ParsedTransaction, ParsedStatement, PDFParseError


def _first_match(candidates: list, keywords: list) -> Optional[str]:
    for c in candidates:
        if any(kw in c.lower() for kw in keywords):
            return c
    return None


def _currency_from_headers(columns: dict, df: pd.DataFrame) -> Optional[str]:
    """
    Try to infer a statement-level currency from column headers or the first few data rows.
    Returns ISO 3-letter code or None. Never guesses — only explicit symbols/codes.
    """
    # Check column header names for embedded currency
    for col_name in df.columns:
        c = extract_currency_from_amount(str(col_name))
        if c:
            return c

    # Sample the first 10 non-null amount values across debit/credit/balance columns
    for col_key in ('debit', 'credit', 'balance'):
        col = columns.get(col_key)
        if not col:
            continue
        for val in df[col].dropna().head(10):
            c = extract_currency_from_amount(str(val))
            if c:
                return c

    return None


def find_columns(df: pd.DataFrame) -> dict:
    """
    Find relevant columns in dataframe by keyword matching on header names.
    Returns dict with keys: date, description, debit, credit, balance.

    Strong (full-word) keywords are tried before short abbreviations
    ('cr', 'dr', 'wd', 'in', 'out', 'dep'), and a column already assigned
    to date/description is excluded from the debit/credit/balance search -
    otherwise a narration-style header like "Description" (which contains
    the substring "cr") can get mis-matched as the Credit column before the
    real "Credit" column is even checked.
    """
    columns = {
        'date': None,
        'description': None,
        'debit': None,
        'credit': None,
        'balance': None,
    }

    df_cols = list(df.columns)

    date_candidates = [c for c in df_cols if any(x in c.lower() for x in ['date', 'txn', 'value'])]
    columns['date'] = date_candidates[0] if date_candidates else df_cols[0]

    desc_candidates = [c for c in df_cols if any(x in c.lower() for x in ['description', 'narration', 'particulars', 'remarks'])]
    columns['description'] = desc_candidates[0] if desc_candidates else (df_cols[1] if len(df_cols) > 1 else None)

    remaining = [c for c in df_cols if c not in (columns['date'], columns['description'])]

    columns['debit'] = (
        _first_match(remaining, ['debit', 'withdrawal'])
        or _first_match(remaining, ['wd', 'dr', 'out'])
    )
    columns['credit'] = (
        _first_match(remaining, ['credit', 'deposit'])
        or _first_match(remaining, ['dep', 'cr', 'in'])
    )
    columns['balance'] = _first_match(remaining, ['balance', 'bal'])

    return columns


def _infer_opening_closing(statement: ParsedStatement) -> None:
    """
    Derive opening/closing balance from the statement's own running balance
    column, when present. Never invented: opening = balance before the first
    transaction's debit/credit was applied; closing = last row's balance.
    """
    txns = [t for t in statement.transactions if t.balance is not None]
    if not txns:
        return

    first = txns[0]
    statement.opening_balance = first.balance - (first.credit or Decimal(0)) + (first.debit or Decimal(0))
    statement.closing_balance = txns[-1].balance


def _parse_dataframe(df: pd.DataFrame, statement: ParsedStatement, source_type: str = "csv") -> None:
    """Shared row-extraction logic for CSV/Excel/JSON (all become a DataFrame)."""
    statement.pages_total = 1
    statement.extraction_method = source_type

    if df.empty:
        statement.errors.append(PDFParseError(1, "empty_file"))
        return

    columns = find_columns(df)
    if not columns['date'] or not columns['description']:
        statement.errors.append(PDFParseError(1, "missing_required_columns"))
        return

    # Statement-level currency: try headers first, then row samples
    statement.currency = _currency_from_headers(columns, df)

    for idx, row in df.iterrows():
        try:
            txn_date = normalize_date(row[columns['date']])
            description = clean_description(row[columns['description']])

            raw_debit = str(row[columns['debit']]) if columns['debit'] else None
            raw_credit = str(row[columns['credit']]) if columns['credit'] else None

            debit = normalize_amount(row[columns['debit']]) if columns['debit'] else None
            credit = normalize_amount(row[columns['credit']]) if columns['credit'] else None
            balance = normalize_amount(row[columns['balance']]) if columns['balance'] else None

            if not any([debit, credit]):
                continue

            # Per-row currency: row-level symbol overrides statement-level
            row_currency = (
                extract_currency_from_amount(raw_debit)
                or extract_currency_from_amount(raw_credit)
                or statement.currency
            )

            statement.transactions.append(ParsedTransaction(
                txn_date=txn_date,
                description=description,
                debit=debit,
                credit=credit,
                balance=balance,
                raw_text=str(row.to_dict()),
                page=1,
                row_index=idx + 1,
                currency=row_currency,
                raw_debit=raw_debit,
                raw_credit=raw_credit,
            ))

        except (ValueError, KeyError):
            continue

    statement.pages_parsed = 1 if statement.transactions else 0
    _infer_opening_closing(statement)


def parse_csv(file_path: str) -> ParsedStatement:
    """Parse CSV statement"""
    statement = ParsedStatement()
    try:
        df = pd.read_csv(file_path)
        _parse_dataframe(df, statement, source_type="csv")
    except Exception as e:
        statement.errors.append(PDFParseError(1, f"csv_read_error: {str(e)}"))
    return statement


def parse_excel(file_path: str) -> ParsedStatement:
    """Parse Excel statement (XLSX or XLS)"""
    statement = ParsedStatement()
    try:
        df = pd.read_excel(file_path, sheet_name=0)
        _parse_dataframe(df, statement, source_type="excel")
    except Exception as e:
        statement.errors.append(PDFParseError(1, f"excel_read_error: {str(e)}"))
    return statement


def parse_json(file_path: str) -> ParsedStatement:
    """
    Parse JSON statement: a JSON array of transaction objects or
    {"transactions": [...], "currency": "USD", ...} envelope.
    Field names are detected the same fuzzy way as CSV/Excel headers.
    """
    statement = ParsedStatement()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Support envelope with metadata
        if isinstance(data, dict):
            # Extract statement-level metadata from envelope
            if data.get("currency"):
                statement.currency = str(data["currency"]).strip().upper()
            records = data.get("transactions", data)
        else:
            records = data

        if not isinstance(records, list):
            statement.errors.append(PDFParseError(1, "unrecognized_json_structure"))
            return statement

        df = pd.json_normalize(records)
        _parse_dataframe(df, statement, source_type="json")

        # JSON envelope currency overrides header-detected currency (more authoritative)
        if isinstance(data, dict) and data.get("currency"):
            statement.currency = str(data["currency"]).strip().upper()

    except Exception as e:
        statement.errors.append(PDFParseError(1, f"json_read_error: {str(e)}"))
    return statement
