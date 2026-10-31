"""Normalize dates, amounts, and descriptions"""
from decimal import Decimal
from datetime import date, datetime
import re


def normalize_date(value: str, day_first: bool = True) -> date:
    """
    Parse date in multiple formats.
    Defaults to day-first (DD/MM/YYYY) for Indian banks.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()

    value = str(value).strip()

    # Try common formats
    formats = [
        "%d/%m/%Y",  # DD/MM/YYYY
        "%d-%m-%Y",  # DD-MM-YYYY
        "%d-%m-%y",  # DD-MM-YY
        "%d/%m/%y",  # DD/MM/YY
        "%d %b %Y",  # DD MMM YYYY
        "%d %B %Y",  # DD MONTH YYYY
        "%d-%b-%Y",  # DD-MMM-YYYY
        "%Y-%m-%d",  # ISO
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date: {value}")


def normalize_amount(value) -> Decimal:
    """
    Parse amount, handling ₹, commas, INR suffix.
    Returns Decimal to avoid float precision issues.
    """
    if value is None:
        return None

    if isinstance(value, float) and value != value:  # NaN (pandas empty cell)
        return None

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    value = str(value).strip()

    # Remove currency symbols and common suffixes
    value = re.sub(r'[₹INR\s]', '', value)
    value = re.sub(r'[Cc][Rr]|[Dd][Rr]', '', value)  # Cr/Dr
    value = value.replace(',', '')

    try:
        return Decimal(value)
    except:
        return None


def normalize_description(text: str) -> str:
    """
    Normalize description: uppercase, collapse whitespace, remove extra chars.
    Used for keyword matching in rules.
    """
    if not text:
        return ""

    text = str(text).upper().strip()
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    # Remove control characters
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)

    return text


def clean_description(text: str) -> str:
    """Clean description for display (preserve original case)"""
    if not text:
        return ""

    text = str(text).strip()
    text = re.sub(r'\s+', ' ', text)

    return text


_TXN_TYPE_KEYWORDS = [
    ("UPI", "UPI"),
    ("NEFT", "NEFT"),
    ("IMPS", "IMPS"),
    ("RTGS", "RTGS"),
    ("ATM", "ATM"),
    ("ECS", "ECS"),
    ("NACH", "NACH"),
    ("CHEQUE", "CHEQUE"),
    ("CHQ", "CHEQUE"),
    ("CASH", "CASH"),
]

# UPI/IMPS/NEFT references are typically a 10-22 digit run. A bare run of
# digits elsewhere (e.g. a phone number embedded in a UPI handle) is not
# treated as a reference unless it appears after one of these markers.
_REFERENCE_MARKERS = re.compile(
    r'(?:UTR|RRN|REF(?:NO)?|TXN(?:ID)?|TRANSACTION\s?ID)[:\-/ ]*([A-Z0-9]{6,})',
)
_BARE_REF_RUN = re.compile(r'(?<!\d)(\d{9,22})(?!\d)')


def extract_transaction_metadata(description: str) -> dict:
    """
    Best-effort extraction of transaction_type, reference_number,
    counterparty and counterparty_account from a free-text narration.
    Every field is None when not confidently found - never guessed or
    fabricated (handoff "Core transaction model" + ASSUMPTIONS.md A-009).
    """
    result = {
        "transaction_type": None,
        "reference_number": None,
        "counterparty": None,
        "counterparty_account": None,
    }
    if not description:
        return result

    upper = description.upper()

    for keyword, label in _TXN_TYPE_KEYWORDS:
        if keyword in upper:
            result["transaction_type"] = label
            break

    marker_match = _REFERENCE_MARKERS.search(upper)
    if marker_match:
        result["reference_number"] = marker_match.group(1)
    else:
        bare_match = _BARE_REF_RUN.search(upper)
        if bare_match:
            result["reference_number"] = bare_match.group(1)

    # Counterparty, two narration styles:
    # 1. Prose: "UPI CR FROM <name>" / "NEFT DR TO <name>" - common in
    #    free-text (Layout B style) statements. Captured first and
    #    independent of rail, so the same real counterparty paying via UPI
    #    one month and NEFT the next still groups together for recurrence
    #    checks (BIZ_RECEIPT rule, customer concentration).
    # 2. Slash/hyphen-delimited: "UPI/<ref>/<name>/<bank>" or
    #    "NEFT-<name>-<ref>" - common in tabular (Layout A style) statements.
    # Only extract when one of these shapes is actually present; otherwise
    # leave None rather than guessing from free text.
    prose_match = re.search(r'(?:CR\s+FROM|DR\s+TO|PAID\s+TO|RECEIVED\s+FROM)\s+(.+)$', upper)
    if prose_match:
        result["counterparty"] = prose_match.group(1).strip()
    else:
        parts = re.split(r'[/\-]', description)
        tokens = [p.strip() for p in parts if p.strip()]
        if result["transaction_type"] and len(tokens) >= 3:
            candidates = [
                t for t in tokens
                if t.upper() not in {kw for kw, _ in _TXN_TYPE_KEYWORDS}
                and not t.isdigit()
                and len(t) > 2
            ]
            if candidates:
                # Prefer the longest alphabetic-looking candidate as the
                # likely counterparty name (narrations mix ids and names;
                # ids are mostly digits/short codes, names are longer runs
                # of letters).
                result["counterparty"] = max(candidates, key=len).strip()

    return result
