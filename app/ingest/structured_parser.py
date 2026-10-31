"""CSV, Excel, and JSON statement parser using pandas"""
import json
import pandas as pd
from decimal import Decimal
from datetime import date
from typing import Optional, List
from app.ingest.normalize import normalize_date, normalize_amount, clean_description
from app.ingest.pdf_parser import ParsedTransaction, ParsedStatement, PDFParseError


def find_columns(df: pd.DataFrame) -> dict:
    """
    Find relevant columns in dataframe by keyword matching on header names.
    Returns dict with keys: date, description, debit, credit, balance
    """
    columns = {
        'date': None,
        'description': None,
        'debit': None,
        'credit': None,
        'balance': None,
    }

    df_cols = list(df.columns)

    # Date column
    date_candidates = [c for c in df_cols if any(x in c.lower() for x in ['date', 'txn', 'value'])]
    columns['date'] = date_candidates[0] if date_candidates else df_cols[0]

    # Description column
    desc_candidates = [c for c in df_cols if any(x in c.lower() for x in ['description', 'narration', 'particulars', 'remarks'])]
    columns['description'] = desc_candidates[0] if desc_candidates else (df_cols[1] if len(df_cols) > 1 else None)

    # Debit column
    debit_candidates = [c for c in df_cols if any(x in c.lower() for x in ['debit', 'withdrawal', 'wd', 'dr', 'out'])]
    columns['debit'] = debit_candidates[0] if debit_candidates else None

    # Credit column
    credit_candidates = [c for c in df_cols if any(x in c.lower() for x in ['credit', 'deposit', 'dep', 'cr', 'in'])]
    columns['credit'] = credit_candidates[0] if credit_candidates else None

    # Balance column
    balance_candidates = [c for c in df_cols if any(x in c.lower() for x in ['balance', 'bal'])]
    columns['balance'] = balance_candidates[0] if balance_candidates else None

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


def _parse_dataframe(df: pd.DataFrame, statement: ParsedStatement) -> None:
    """Shared row-extraction logic for CSV/Excel/JSON (all become a DataFrame)."""
    statement.pages_total = 1

    if df.empty:
        statement.errors.append(PDFParseError(1, "empty_file"))
        return

    columns = find_columns(df)
    if not columns['date'] or not columns['description']:
        statement.errors.append(PDFParseError(1, "missing_required_columns"))
        return

    for idx, row in df.iterrows():
        try:
            txn_date = normalize_date(row[columns['date']])
            description = clean_description(row[columns['description']])
            debit = normalize_amount(row[columns['debit']]) if columns['debit'] else None
            credit = normalize_amount(row[columns['credit']]) if columns['credit'] else None
            balance = normalize_amount(row[columns['balance']]) if columns['balance'] else None

            if not any([debit, credit]):
                continue  # Skip rows with no amount

            statement.transactions.append(ParsedTransaction(
                txn_date=txn_date,
                description=description,
                debit=debit,
                credit=credit,
                balance=balance,
                raw_text=str(row.to_dict()),
                page=1,
                row_index=idx + 1,
            ))

        except (ValueError, KeyError):
            continue  # Skip malformed rows

    statement.pages_parsed = 1 if statement.transactions else 0
    _infer_opening_closing(statement)


def parse_csv(file_path: str) -> ParsedStatement:
    """Parse CSV statement"""
    statement = ParsedStatement()
    try:
        df = pd.read_csv(file_path)
        _parse_dataframe(df, statement)
    except Exception as e:
        statement.errors.append(PDFParseError(1, f"csv_read_error: {str(e)}"))
    return statement


def parse_excel(file_path: str) -> ParsedStatement:
    """Parse Excel statement (XLSX or XLS)"""
    statement = ParsedStatement()
    try:
        df = pd.read_excel(file_path, sheet_name=0)
        _parse_dataframe(df, statement)
    except Exception as e:
        statement.errors.append(PDFParseError(1, f"excel_read_error: {str(e)}"))
    return statement


def parse_json(file_path: str) -> ParsedStatement:
    """
    Parse JSON statement: a JSON array of transaction objects, e.g.
    [{"date": "...", "narration": "...", "amount": -850.0}, ...]
    Field names are detected the same fuzzy way as CSV/Excel headers.
    """
    statement = ParsedStatement()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data.get("transactions", data) if isinstance(data, dict) else data
        if not isinstance(records, list):
            statement.errors.append(PDFParseError(1, "unrecognized_json_structure"))
            return statement

        df = pd.json_normalize(records)
        _parse_dataframe(df, statement)
    except Exception as e:
        statement.errors.append(PDFParseError(1, f"json_read_error: {str(e)}"))
    return statement
