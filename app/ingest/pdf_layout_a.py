"""
PDF Layout A: table-based statement (e.g. "Lotus Bank" savings statement).
Header block as plain text, transactions as a bordered table with columns
[Date, Description, Debit, Credit, Balance].
"""
import re
import pdfplumber
from app.ingest.normalize import normalize_date, normalize_amount, clean_description, detect_currency_in_text
from app.ingest.pdf_parser import ParsedTransaction, ParsedStatement, PDFParseError

SIGNATURE = "Savings Account Statement"


def can_parse(first_page_text: str) -> bool:
    return SIGNATURE in (first_page_text or "")


def _parse_header(text: str) -> dict:
    header = {}
    m = re.search(r"Account Holder:\s*(.+)", text)
    header["holder_name"] = m.group(1).strip() if m else None

    m = re.search(r"Account Number:\s*(\S+)", text)
    header["account_number"] = m.group(1).strip() if m else None

    m = re.search(r"Bank:\s*(.+)", text)
    header["bank_name"] = m.group(1).strip() if m else None

    m = re.search(r"Statement Period:\s*(\d{2} \w{3} \d{4}) to (\d{2} \w{3} \d{4})", text)
    if m:
        header["period_start"] = normalize_date(m.group(1))
        header["period_end"] = normalize_date(m.group(2))
    else:
        header["period_start"] = None
        header["period_end"] = None

    # Balance lines may have prefix symbol (Rs., ₹) or suffix ISO code (OMR, AED, INR …)
    m = re.search(r"Opening Balance:\s*(?:Rs\.?\s*)?([\d,]+\.\d+)(?:\s+[A-Z]{3})?", text)
    header["opening_balance"] = normalize_amount(m.group(1)) if m else None

    m = re.search(r"Closing Balance:\s*(?:Rs\.?\s*)?([\d,]+\.\d+)(?:\s+[A-Z]{3})?", text)
    header["closing_balance"] = normalize_amount(m.group(1)) if m else None

    header["currency"] = detect_currency_in_text(text)
    return header


def parse_pdf(file_path: str) -> ParsedStatement:
    statement = ParsedStatement()

    with pdfplumber.open(file_path) as pdf:
        statement.pages_total = len(pdf.pages)

        first_page_text = pdf.pages[0].extract_text() or ""
        header = _parse_header(first_page_text)
        statement.holder_name = header["holder_name"]
        statement.account_number = header["account_number"]
        statement.bank_name = header["bank_name"]
        statement.period_start = header["period_start"]
        statement.period_end = header["period_end"]
        statement.opening_balance = header["opening_balance"]
        statement.closing_balance = header["closing_balance"]
        statement.currency = header.get("currency")

        if not header["holder_name"] or not header["account_number"]:
            statement.errors.append(PDFParseError(1, "missing_header_fields"))

        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text:
                statement.errors.append(PDFParseError(page_num, "no_text_layer_scanned_page"))
                continue

            tables = page.extract_tables()
            if not tables:
                statement.errors.append(PDFParseError(page_num, "no_transactions_extracted"))
                continue

            page_had_rows = False
            for table in tables:
                if not table or len(table) < 2:
                    continue
                for row_idx, row in enumerate(table[1:], 1):
                    if len(row) < 5 or row[0] is None:
                        continue
                    try:
                        txn_date = normalize_date(row[0])
                    except ValueError:
                        continue  # header/footer row, not a transaction

                    description = clean_description(row[1])
                    debit = normalize_amount(row[2]) if row[2] and row[2] != "-" else None
                    credit = normalize_amount(row[3]) if row[3] and row[3] != "-" else None
                    balance = normalize_amount(row[4]) if row[4] and row[4] != "-" else None

                    if debit is None and credit is None:
                        continue

                    statement.transactions.append(ParsedTransaction(
                        txn_date=txn_date,
                        description=description,
                        debit=debit,
                        credit=credit,
                        balance=balance,
                        raw_text=" | ".join(str(c) for c in row),
                        page=page_num,
                        row_index=row_idx,
                    ))
                    page_had_rows = True

            if not page_had_rows:
                statement.errors.append(PDFParseError(page_num, "no_transactions_extracted"))
            else:
                statement.pages_parsed += 1

    return statement
