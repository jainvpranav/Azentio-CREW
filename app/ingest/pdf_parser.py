"""PDF statement parser using pdfplumber"""
import pdfplumber
import re
from decimal import Decimal
from datetime import date
from typing import Optional, List, Tuple
from app.ingest.normalize import normalize_date, normalize_amount, clean_description


class PDFParseError:
    def __init__(self, page: int, reason: str):
        self.page = page
        self.reason = reason


class ParsedTransaction:
    def __init__(
        self,
        txn_date: date,
        description: str,
        debit: Optional[Decimal] = None,
        credit: Optional[Decimal] = None,
        balance: Optional[Decimal] = None,
        raw_text: str = "",
        page: int = 0,
        row_index: int = 0,
    ):
        self.txn_date = txn_date
        self.description = description
        self.debit = debit
        self.credit = credit
        self.balance = balance
        self.raw_text = raw_text
        self.page = page
        self.row_index = row_index


class ParsedStatement:
    def __init__(
        self,
        account_number: Optional[str] = None,
        holder_name: Optional[str] = None,
        bank_name: Optional[str] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        opening_balance: Optional[Decimal] = None,
        closing_balance: Optional[Decimal] = None,
        transactions: Optional[List[ParsedTransaction]] = None,
        errors: Optional[List[PDFParseError]] = None,
        pages_parsed: int = 0,
        pages_total: int = 0,
    ):
        self.account_number = account_number
        self.holder_name = holder_name
        self.bank_name = bank_name
        self.period_start = period_start
        self.period_end = period_end
        self.opening_balance = opening_balance
        self.closing_balance = closing_balance
        self.transactions = transactions or []
        self.errors = errors or []
        self.pages_parsed = pages_parsed
        self.pages_total = pages_total


def parse_pdf(file_path: str) -> ParsedStatement:
    """
    Parse PDF bank statement.

    Currently supports basic table extraction.
    Extend for layout-specific parsers (Layout A, Layout B from BUILD_PLAN).
    """

    statement = ParsedStatement()

    try:
        with pdfplumber.open(file_path) as pdf:
            statement.pages_total = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages):
                page_num_1indexed = page_num + 1

                # Check if page has text
                text = page.extract_text()
                if not text:
                    statement.errors.append(
                        PDFParseError(page_num_1indexed, "no_text_layer_scanned_page")
                    )
                    continue

                # Try to extract table
                tables = page.extract_tables()
                if not tables:
                    statement.errors.append(
                        PDFParseError(page_num_1indexed, "no_transactions_extracted")
                    )
                    continue

                # Extract transactions from table
                for table in tables:
                    if not table:
                        continue

                    # Assume first row is header, skip it
                    for row_idx, row in enumerate(table[1:], 1):
                        try:
                            # Simple extraction: assumes table columns are
                            # [date, description, debit, credit, balance]
                            # Adjust based on actual bank statement format

                            if len(row) < 4:
                                continue

                            # This is a placeholder - real parsers would handle
                            # multiple column orders and formats
                            txn_date = normalize_date(row[0])
                            description = clean_description(row[1])
                            debit = normalize_amount(row[2])
                            credit = normalize_amount(row[3])
                            balance = normalize_amount(row[4]) if len(row) > 4 else None

                            if not any([debit, credit]):
                                continue  # Skip rows with no amount

                            txn = ParsedTransaction(
                                txn_date=txn_date,
                                description=description,
                                debit=debit,
                                credit=credit,
                                balance=balance,
                                raw_text=" | ".join(str(c) for c in row),
                                page=page_num_1indexed,
                                row_index=row_idx,
                            )
                            statement.transactions.append(txn)

                        except (ValueError, IndexError) as e:
                            # Skip malformed rows
                            continue

                if len(statement.transactions) > 0 or not tables:
                    statement.pages_parsed += 1

    except Exception as e:
        statement.errors.append(PDFParseError(1, f"pdf_read_error: {str(e)}"))

    return statement
