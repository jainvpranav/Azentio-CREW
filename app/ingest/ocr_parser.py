"""OCR parser for image files (PNG/JPG/JPEG) and scanned PDF page assistance."""
import re
from decimal import Decimal
from datetime import date
from typing import List, Optional, Tuple

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from app.ingest.pdf_parser import ParsedStatement, ParsedTransaction, PDFParseError
from app.ingest.normalize import (
    normalize_date, normalize_amount, clean_description,
    extract_currency_from_amount,
)

_DATE_RE = re.compile(
    r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}'
    r'|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}'
    r'|\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r'[₹\$€£¥]?\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,2})'
    r'|\d+\.\d{2}'
)


def ocr_pil_image(img) -> Tuple[str, Optional[float]]:
    """
    OCR a PIL Image. Returns (text, avg_confidence).
    avg_confidence is 0-100 from tesseract; None if unavailable.
    """
    if not OCR_AVAILABLE:
        raise RuntimeError("pytesseract/Pillow not installed; OCR unavailable")
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        confs = [int(c) for c in data.get('conf', []) if str(c).lstrip('-').isdigit() and int(c) >= 0]
        avg_conf = sum(confs) / len(confs) if confs else None
    except Exception:
        avg_conf = None
    text = pytesseract.image_to_string(img)
    return text, avg_conf


def parse_ocr_text(text: str, page: int = 1) -> List[ParsedTransaction]:
    """
    Extract transactions from OCR'd text using date + amount heuristics.
    Only produces rows where a parseable date and at least one amount are present.
    """
    transactions = []
    lines = (text or "").split('\n')

    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        date_match = _DATE_RE.search(line)
        if not date_match:
            continue

        amounts = _AMOUNT_RE.findall(line)
        if not amounts:
            continue

        try:
            txn_date = normalize_date(date_match.group(0))
        except ValueError:
            continue

        # Remove the date from description; remove amounts too
        desc_text = line[date_match.end():].strip()
        for amt in amounts:
            desc_text = desc_text.replace(amt, '').strip()
        description = clean_description(desc_text) or line

        currency = next(
            (extract_currency_from_amount(a) for a in amounts if extract_currency_from_amount(a)),
            None,
        )

        debit = credit = balance = None
        if len(amounts) >= 3:
            debit = normalize_amount(amounts[0])
            credit = normalize_amount(amounts[1])
            balance = normalize_amount(amounts[2])
        elif len(amounts) == 2:
            balance = normalize_amount(amounts[-1])
            upper = line.upper()
            if re.search(r'\bCR\b|\bCREDIT\b|\bDEP\b', upper):
                credit = normalize_amount(amounts[0])
            elif re.search(r'\bDR\b|\bDEBIT\b|\bWD\b|\bWITHD', upper):
                debit = normalize_amount(amounts[0])
            else:
                credit = normalize_amount(amounts[0])
        elif len(amounts) == 1:
            credit = normalize_amount(amounts[0])

        if not any([debit, credit]):
            continue

        transactions.append(ParsedTransaction(
            txn_date=txn_date,
            description=description,
            debit=debit,
            credit=credit,
            balance=balance,
            raw_text=line,
            page=page,
            row_index=idx + 1,
            currency=currency,
            raw_debit=amounts[0] if len(amounts) >= 3 else None,
            raw_credit=amounts[1] if len(amounts) >= 3 else (amounts[0] if credit else None),
        ))

    return transactions


def parse_image(file_path: str) -> ParsedStatement:
    """Parse a bank statement image (PNG/JPG/JPEG) using OCR."""
    statement = ParsedStatement(extraction_method="image_ocr")
    statement.pages_total = 1

    if not OCR_AVAILABLE:
        statement.errors.append(
            PDFParseError(1, "ocr_not_available: install pytesseract and Pillow")
        )
        return statement

    try:
        img = Image.open(file_path)
        text, confidence = ocr_pil_image(img)

        if not text or not text.strip():
            statement.errors.append(PDFParseError(1, "ocr_empty_result"))
            return statement

        statement.transactions = parse_ocr_text(text, page=1)
        statement.pages_parsed = 1 if statement.transactions else 0
        statement.ocr_confidence = confidence

        conf_label = f" (confidence: {confidence:.0f}%)" if confidence is not None else ""
        if statement.transactions:
            statement.errors.append(
                PDFParseError(1, f"ocr_completed{conf_label}")
            )
        else:
            statement.errors.append(
                PDFParseError(1, f"ocr_no_transactions_found{conf_label}")
            )

    except RuntimeError as exc:
        statement.errors.append(PDFParseError(1, str(exc)))
    except Exception as exc:
        statement.errors.append(PDFParseError(1, f"image_ocr_error: {exc}"))

    return statement
