"""PDF statement parser using pdfplumber"""
import pdfplumber
import re
from decimal import Decimal
from datetime import date
from typing import List, Optional, Tuple
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
        currency: Optional[str] = None,
        raw_debit: Optional[str] = None,
        raw_credit: Optional[str] = None,
        custom_metadata: Optional[dict] = None,
        source_data: Optional[dict] = None,
    ):
        self.txn_date = txn_date
        self.description = description
        self.debit = debit
        self.credit = credit
        self.balance = balance
        self.raw_text = raw_text
        self.page = page
        self.row_index = row_index
        self.currency = currency
        self.raw_debit = raw_debit
        self.raw_credit = raw_credit
        self.custom_metadata = custom_metadata  # unmapped institution-specific fields
        self.source_data = source_data          # complete original row {header: value}


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
        currency: Optional[str] = None,
        extraction_method: str = "unknown",
        ocr_confidence: Optional[float] = None,
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
        self.currency = currency
        self.extraction_method = extraction_method
        self.ocr_confidence = ocr_confidence


def _try_ocr_page(page, page_num: int) -> Tuple[List[ParsedTransaction], Optional[float]]:
    """
    Attempt to OCR a scanned PDF page.
    Returns (transactions, avg_confidence). Returns ([], None) if OCR is unavailable.
    """
    try:
        from app.ingest.ocr_parser import OCR_AVAILABLE, ocr_pil_image, parse_ocr_text
    except ImportError:
        return [], None

    if not OCR_AVAILABLE:
        return [], None

    pil_image = None

    # Try pdfplumber's built-in page rendering (needs Wand/ImageMagick)
    try:
        rendered = page.to_image(resolution=200)
        pil_image = rendered.original
    except Exception:
        pass

    if pil_image is None:
        # Try pdf2image as fallback
        try:
            import pdf2image
            images = pdf2image.convert_from_path(
                page.pdf.stream.name, first_page=page_num, last_page=page_num, dpi=200
            )
            if images:
                pil_image = images[0]
        except Exception:
            pass

    if pil_image is None:
        return [], None

    text, confidence = ocr_pil_image(pil_image)
    txns = parse_ocr_text(text, page=page_num) if text else []
    return txns, confidence


def parse_pdf(file_path: str) -> ParsedStatement:
    """
    Parse PDF bank statement.
    Tries native text extraction first; falls back to OCR for scanned pages.
    """
    statement = ParsedStatement(extraction_method="native_pdf")
    ocr_confidences = []
    pages_ocr_used = 0

    try:
        with pdfplumber.open(file_path) as pdf:
            statement.pages_total = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages):
                page_num_1indexed = page_num + 1

                text = page.extract_text()
                if not text:
                    # Scanned page — attempt OCR fallback
                    ocr_txns, confidence = _try_ocr_page(page, page_num_1indexed)
                    if ocr_txns:
                        statement.transactions.extend(ocr_txns)
                        statement.pages_parsed += 1
                        pages_ocr_used += 1
                        if confidence is not None:
                            ocr_confidences.append(confidence)
                        statement.errors.append(
                            PDFParseError(page_num_1indexed,
                                          f"scanned_page_ocr_used (confidence: {confidence:.0f}%)" if confidence else "scanned_page_ocr_used")
                        )
                    else:
                        statement.errors.append(
                            PDFParseError(page_num_1indexed, "no_text_layer_scanned_page")
                        )
                    continue

                tables = page.extract_tables()
                if not tables:
                    statement.errors.append(
                        PDFParseError(page_num_1indexed, "no_transactions_extracted")
                    )
                    continue

                for table in tables:
                    if not table:
                        continue

                    for row_idx, row in enumerate(table[1:], 1):
                        try:
                            if len(row) < 4:
                                continue

                            raw_debit = str(row[2]) if row[2] else None
                            raw_credit = str(row[3]) if row[3] else None

                            txn_date = normalize_date(row[0])
                            description = clean_description(row[1])
                            debit = normalize_amount(row[2])
                            credit = normalize_amount(row[3])
                            balance = normalize_amount(row[4]) if len(row) > 4 else None

                            if not any([debit, credit]):
                                continue

                            from app.ingest.normalize import extract_currency_from_amount
                            currency = (extract_currency_from_amount(raw_debit)
                                        or extract_currency_from_amount(raw_credit))

                            txn = ParsedTransaction(
                                txn_date=txn_date,
                                description=description,
                                debit=debit,
                                credit=credit,
                                balance=balance,
                                raw_text=" | ".join(str(c) for c in row),
                                page=page_num_1indexed,
                                row_index=row_idx,
                                currency=currency,
                                raw_debit=raw_debit,
                                raw_credit=raw_credit,
                            )
                            statement.transactions.append(txn)

                        except (ValueError, IndexError):
                            continue

                if len(statement.transactions) > 0 or not tables:
                    statement.pages_parsed += 1

    except Exception as e:
        statement.errors.append(PDFParseError(1, f"pdf_read_error: {str(e)}"))

    if pages_ocr_used > 0:
        if pages_ocr_used == statement.pages_total:
            statement.extraction_method = "ocr_pdf"
        else:
            statement.extraction_method = "native_and_ocr_pdf"
        if ocr_confidences:
            statement.ocr_confidence = sum(ocr_confidences) / len(ocr_confidences)

    return statement
