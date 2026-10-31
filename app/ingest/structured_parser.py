"""CSV, Excel, and JSON statement parser using pandas"""
import json
import re
import pandas as pd
from decimal import Decimal
from datetime import date
from typing import Optional, List, Dict, Tuple
from app.ingest.normalize import (
    normalize_date, normalize_amount, clean_description,
    extract_currency_from_amount, KNOWN_ISO_CURRENCIES,
    normalize_header, _clean_header,
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
    for col_name in df.columns:
        c = extract_currency_from_amount(str(col_name))
        if c:
            return c

    for col_key in ('debit', 'credit', 'balance'):
        col = columns.get(col_key)
        if not col:
            continue
        for val in df[col].dropna().head(10):
            c = extract_currency_from_amount(str(val))
            if c:
                return c

    return None


def map_headers(df: pd.DataFrame) -> Tuple[Dict[str, str], Dict[str, List[str]], List[str]]:
    """
    Map DataFrame column names to internal keys using normalize_header().

    Returns:
      column_map   - {internal_key: col_name} for unambiguous 1-to-1 matches
      ambiguous    - {internal_key: [col_names]} when multiple columns map to the same key
      unmapped     - [col_names] that normalize_header() returned None for

    Rules:
    - Each internal key is assigned at most one source column (first match wins).
    - When a second column resolves to the same key, both are recorded in ambiguous
      and neither is used as the primary, preserving both values for audit.
    - unmapped columns are stored verbatim in custom_metadata on every row.
    """
    column_map: Dict[str, str] = {}
    ambiguous: Dict[str, List[str]] = {}
    unmapped: List[str] = []

    for col in df.columns:
        key = normalize_header(str(col))
        if key is None:
            unmapped.append(col)
        elif key in ambiguous:
            ambiguous[key].append(col)
        elif key in column_map:
            # Second column maps to same key — move to ambiguous, clear primary
            ambiguous[key] = [column_map.pop(key), col]
        else:
            column_map[key] = col

    return column_map, ambiguous, unmapped


def find_columns(df: pd.DataFrame) -> dict:
    """
    Keyword-based column finder kept for backward compatibility (used by PDF table
    extraction paths). New code should use map_headers() instead.
    """
    columns = {
        'date': None, 'description': None,
        'debit': None, 'credit': None, 'balance': None,
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

    # Primary: use normalize_header-based mapping for international/institution-aware matching.
    # Falls back to find_columns() for any key not resolved by the alias dictionary.
    column_map, ambiguous, unmapped = map_headers(df)

    # Record any ambiguous mappings as a diagnostic
    if ambiguous:
        for key, cols in ambiguous.items():
            statement.errors.append(PDFParseError(1, f"ambiguous_header_{key}: {cols}"))

    # For keys not resolved by normalize_header, fall back to keyword scan
    legacy = find_columns(df)
    for key in ('transaction_date', 'description', 'debit', 'credit', 'balance'):
        short = 'date' if key == 'transaction_date' else key
        if key not in column_map and short in legacy and legacy[short]:
            column_map[key] = legacy[short]
            # Remove from unmapped if it ended up there
            if legacy[short] in unmapped:
                unmapped.remove(legacy[short])

    date_col = column_map.get('transaction_date')
    desc_col = column_map.get('description')

    if not date_col or not desc_col:
        statement.errors.append(PDFParseError(1, "missing_required_columns"))
        return

    debit_col   = column_map.get('debit')
    credit_col  = column_map.get('credit')
    balance_col = column_map.get('balance')
    amount_col  = column_map.get('amount')

    # Statement-level currency: try headers, then row samples
    statement.currency = _currency_from_headers(
        {'debit': debit_col, 'credit': credit_col, 'balance': balance_col}, df
    )

    # All mapped internal cols — not stored in custom_metadata
    mapped_cols = set(column_map.values())
    # Cols involved in ambiguous mappings — still stored in source_data
    ambiguous_cols = {c for cols in ambiguous.values() for c in cols}

    for idx, row in df.iterrows():
        try:
            txn_date = normalize_date(row[date_col])
            description = clean_description(row[desc_col])

            raw_debit  = str(row[debit_col])  if debit_col  else None
            raw_credit = str(row[credit_col]) if credit_col else None

            debit   = normalize_amount(row[debit_col])   if debit_col   else None
            credit  = normalize_amount(row[credit_col])  if credit_col  else None
            balance = normalize_amount(row[balance_col]) if balance_col else None

            # If no debit/credit columns but a single 'amount' column exists,
            # treat positive as credit and negative as debit (common in some formats)
            if not any([debit, credit]) and amount_col:
                amt = normalize_amount(row[amount_col])
                if amt is not None:
                    if amt >= 0:
                        credit = amt
                        raw_credit = str(row[amount_col])
                    else:
                        debit = abs(amt)
                        raw_debit = str(row[amount_col])

            if not any([debit, credit]):
                continue

            # Per-row currency: row-level symbol overrides statement-level
            row_currency = (
                extract_currency_from_amount(raw_debit)
                or extract_currency_from_amount(raw_credit)
                or statement.currency
            )

            # source_data: complete original row — every header + raw value
            source_data = {str(col): (str(row[col]) if pd.notna(row[col]) else None)
                           for col in df.columns}

            # custom_metadata: unmapped columns + ambiguous collision columns
            custom_metadata = {str(col): source_data[str(col)]
                               for col in (unmapped + list(ambiguous_cols))}
            if ambiguous:
                custom_metadata['_ambiguous_mappings'] = {
                    key: cols for key, cols in ambiguous.items()
                }

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
                custom_metadata=custom_metadata if custom_metadata else None,
                source_data=source_data,
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
