"""CSV, Excel, and JSON statement parser using pandas"""
import pandas as pd
from decimal import Decimal
from datetime import date
from typing import Optional, List
from difflib import SequenceMatcher
from app.ingest.normalize import normalize_date, normalize_amount, clean_description
from app.ingest.pdf_parser import ParsedTransaction, ParsedStatement, PDFParseError


def fuzzy_match(header: str, candidates: List[str], threshold: float = 0.6) -> Optional[str]:
    """
    Fuzzy match header name to column candidates.
    E.g., 'txn_date' matches 'transaction_date', 'Txn Date', etc.
    """
    header_lower = header.lower().replace('_', '').replace(' ', '')

    best_match = None
    best_ratio = threshold

    for candidate in candidates:
        candidate_lower = candidate.lower().replace('_', '').replace(' ', '')
        ratio = SequenceMatcher(None, header_lower, candidate_lower).ratio()

        if ratio > best_ratio:
            best_ratio = ratio
            best_match = candidate

    return best_match


def find_columns(df: pd.DataFrame) -> dict:
    """
    Find relevant columns in dataframe by fuzzy matching.
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
    columns['date'] = fuzzy_match('date', date_candidates) or df_cols[0]

    # Description column
    desc_candidates = [c for c in df_cols if any(x in c.lower() for x in ['description', 'narration', 'particulars', 'remarks'])]
    columns['description'] = fuzzy_match('description', desc_candidates) or (df_cols[1] if len(df_cols) > 1 else None)

    # Debit column
    debit_candidates = [c for c in df_cols if any(x in c.lower() for x in ['debit', 'withdrawal', 'wd', 'dr', 'out'])]
    columns['debit'] = fuzzy_match('debit', debit_candidates)

    # Credit column
    credit_candidates = [c for c in df_cols if any(x in c.lower() for x in ['credit', 'deposit', 'dep', 'cr', 'in'])]
    columns['credit'] = fuzzy_match('credit', credit_candidates)

    # Balance column
    balance_candidates = [c for c in df_cols if any(x in c.lower() for x in ['balance', 'bal'])]
    columns['balance'] = fuzzy_match('balance', balance_candidates)

    return columns


def parse_csv(file_path: str) -> ParsedStatement:
    """Parse CSV statement"""
    statement = ParsedStatement()

    try:
        df = pd.read_csv(file_path)
        statement.pages_total = 1

        if df.empty:
            statement.errors.append(PDFParseError(1, "empty_file"))
            return statement

        columns = find_columns(df)

        if not columns['date'] or not columns['description']:
            statement.errors.append(PDFParseError(1, "missing_required_columns"))
            return statement

        # Parse rows
        for idx, row in df.iterrows():
            try:
                txn_date = normalize_date(row[columns['date']])
                description = clean_description(row[columns['description']])
                debit = normalize_amount(row[columns['debit']]) if columns['debit'] else None
                credit = normalize_amount(row[columns['credit']]) if columns['credit'] else None
                balance = normalize_amount(row[columns['balance']]) if columns['balance'] else None

                if not any([debit, credit]):
                    continue  # Skip rows with no amount

                txn = ParsedTransaction(
                    txn_date=txn_date,
                    description=description,
                    debit=debit,
                    credit=credit,
                    balance=balance,
                    raw_text=str(row.to_dict()),
                    page=1,
                    row_index=idx + 1,
                )
                statement.transactions.append(txn)

            except (ValueError, KeyError) as e:
                continue  # Skip malformed rows

        statement.pages_parsed = 1 if statement.transactions else 0

    except Exception as e:
        statement.errors.append(PDFParseError(1, f"csv_read_error: {str(e)}"))

    return statement


def parse_excel(file_path: str) -> ParsedStatement:
    """Parse Excel statement (XLSX or XLS)"""
    statement = ParsedStatement()

    try:
        # Try to read first sheet
        df = pd.read_excel(file_path, sheet_name=0)
        statement.pages_total = 1

        if df.empty:
            statement.errors.append(PDFParseError(1, "empty_file"))
            return statement

        columns = find_columns(df)

        if not columns['date'] or not columns['description']:
            statement.errors.append(PDFParseError(1, "missing_required_columns"))
            return statement

        # Parse rows
        for idx, row in df.iterrows():
            try:
                txn_date = normalize_date(row[columns['date']])
                description = clean_description(row[columns['description']])
                debit = normalize_amount(row[columns['debit']]) if columns['debit'] else None
                credit = normalize_amount(row[columns['credit']]) if columns['credit'] else None
                balance = normalize_amount(row[columns['balance']]) if columns['balance'] else None

                if not any([debit, credit]):
                    continue

                txn = ParsedTransaction(
                    txn_date=txn_date,
                    description=description,
                    debit=debit,
                    credit=credit,
                    balance=balance,
                    raw_text=str(row.to_dict()),
                    page=1,
                    row_index=idx + 1,
                )
                statement.transactions.append(txn)

            except (ValueError, KeyError) as e:
                continue

        statement.pages_parsed = 1 if statement.transactions else 0

    except Exception as e:
        statement.errors.append(PDFParseError(1, f"excel_read_error: {str(e)}"))

    return statement
