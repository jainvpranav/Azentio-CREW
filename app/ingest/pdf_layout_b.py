"""
PDF Layout B: free-text statement (e.g. "Meridian Co-operative Bank" current
account statement). Header block as plain text, one pipe-delimited line per
transaction: DD-Mon-YYYY | description | CR/DR | amount | balance.
"""
import re
import pdfplumber
from app.ingest.normalize import normalize_date, normalize_amount, clean_description
from app.ingest.pdf_parser import ParsedTransaction, ParsedStatement, PDFParseError

SIGNATURE = "Current Account Statement"

LINE_RE = re.compile(
    r"^(\d{2}-\w{3}-\d{4})\s*\|\s*(.+?)\s*\|\s*(CR|DR)\s*\|\s*([\d,]+\.\d{2})\s*\|\s*([\d,]+\.\d{2})\s*$"
)


def can_parse(first_page_text: str) -> bool:
    return SIGNATURE in (first_page_text or "")


def _parse_header(text: str) -> dict:
    header = {}
    m = re.search(r"Name:\s*(.+)", text)
    header["holder_name"] = m.group(1).strip() if m else None

    m = re.search(r"A/c No:\s*(\S+)", text)
    header["account_number"] = m.group(1).strip() if m else None

    m = re.search(r"^(.+?Bank.*)$", text, re.MULTILINE)
    header["bank_name"] = m.group(1).strip() if m else None

    m = re.search(r"Period:\s*(\d{2}-\w{3}-\d{4}) to (\d{2}-\w{3}-\d{4})", text)
    if m:
        header["period_start"] = normalize_date(m.group(1))
        header["period_end"] = normalize_date(m.group(2))
    else:
        header["period_start"] = None
        header["period_end"] = None

    m = re.search(r"Opening Bal:\s*([\d,]+\.\d{2})", text)
    header["opening_balance"] = normalize_amount(m.group(1)) if m else None

    m = re.search(r"Closing Bal:\s*([\d,]+\.\d{2})", text)
    header["closing_balance"] = normalize_amount(m.group(1)) if m else None

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

        if not header["holder_name"] or not header["account_number"]:
            statement.errors.append(PDFParseError(1, "missing_header_fields"))

        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text:
                statement.errors.append(PDFParseError(page_num, "no_text_layer_scanned_page"))
                continue

            page_had_rows = False
            row_idx = 0
            for line in text.splitlines():
                m = LINE_RE.match(line.strip())
                if not m:
                    continue  # header/footer line

                row_idx += 1
                date_str, desc, side, amount_str, balance_str = m.groups()
                amount = normalize_amount(amount_str)
                debit = amount if side == "DR" else None
                credit = amount if side == "CR" else None

                statement.transactions.append(ParsedTransaction(
                    txn_date=normalize_date(date_str),
                    description=clean_description(desc),
                    debit=debit,
                    credit=credit,
                    balance=normalize_amount(balance_str),
                    raw_text=line.strip(),
                    page=page_num,
                    row_index=row_idx,
                ))
                page_had_rows = True

            if not page_had_rows:
                statement.errors.append(PDFParseError(page_num, "no_transactions_extracted"))
            else:
                statement.pages_parsed += 1

    return statement
