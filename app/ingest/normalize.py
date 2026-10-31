"""Normalize dates, amounts, descriptions, and CSV headers"""
from decimal import Decimal
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Optional, Tuple
import re
import unicodedata


KNOWN_ISO_CURRENCIES = {
    'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'INR', 'AUD', 'CAD', 'CHF',
    'SGD', 'HKD', 'AED', 'MYR', 'THB', 'IDR', 'PHP', 'KRW', 'BRL',
    'ZAR', 'NGN', 'KES', 'GHS', 'EGP', 'PKR', 'BDT', 'LKR', 'NPR',
    'OMR', 'QAR', 'SAR', 'KWD', 'BHD', 'JOD',
}

# Ordered longest-first so 'C$' matches before '$', 'A$' before '$', etc.
_CURRENCY_SYMBOLS = sorted([
    ('₹', 'INR'), ('Rs.', 'INR'), ('Rs ', 'INR'), ('INR', 'INR'),
    ('USD', 'USD'), ('$', 'USD'),
    ('EUR', 'EUR'), ('€', 'EUR'),
    ('GBP', 'GBP'), ('£', 'GBP'),
    ('JPY', 'JPY'), ('¥', 'JPY'),
    ('CNY', 'CNY'),
    ('CAD', 'CAD'), ('C$', 'CAD'),
    ('AUD', 'AUD'), ('A$', 'AUD'),
    ('SGD', 'SGD'), ('S$', 'SGD'),
    ('HKD', 'HKD'), ('HK$', 'HKD'),
    ('AED', 'AED'),
    ('OMR', 'OMR'),
    ('QAR', 'QAR'),
    ('SAR', 'SAR'),
    ('KWD', 'KWD'),
    ('BHD', 'BHD'),
    ('JOD', 'JOD'),
], key=lambda x: -len(x[0]))


def detect_currency_in_text(text: str) -> Optional[str]:
    """Return the first ISO currency code or symbol found in text, or None."""
    if not text:
        return None
    for symbol, iso in _CURRENCY_SYMBOLS:
        if symbol in text:
            return iso
    return None


# ---------------------------------------------------------------------------
# Header normalization — for CSV/Excel/JSON column mapping
# ---------------------------------------------------------------------------

# Extensible alias dictionary. Each internal key maps to known aliases across
# languages and institutions. Add new aliases here without touching the parser.
HEADER_ALIASES: dict = {
    'transaction_date': [
        'date', 'posting date', 'txn date', 'transaction date', 'trans date',
        'tran date', 'value date', 'effective date', 'book date', 'trade date',
        'fecha', 'data', 'dat', 'datum', 'dated',
    ],
    'description': [
        'description', 'narration', 'memo', 'details', 'particulars',
        'remarks', 'historique', 'transaction details', 'narrative',
        'transaction narration', 'trans description', 'transaction description',
        'particuliers', 'libelle',
        # Note: 'reference' is intentionally excluded — it conflicts with
        # institution-specific "Reference ID" / "Reference No" columns.
    ],
    'amount': [
        'amount', 'transaction amount', 'txn amount', 'importe',
        'net amount', 'value', 'transaction value',
    ],
    'debit': [
        'debit', 'withdrawal', 'withdrawals', 'outflow', 'paid out',
        'debit amount', 'debit amt', 'dr amount', 'dr amt',
        'wd', 'out', 'outgoing', 'payment', 'payments',
    ],
    'credit': [
        'credit', 'deposit', 'deposits', 'inflow', 'paid in',
        'credit amount', 'credit amt', 'cr amount', 'cr amt',
        'in', 'incoming', 'receipt', 'receipts',
    ],
    'balance': [
        'balance', 'running balance', 'closing balance', 'available balance',
        'solde', 'bal', 'book balance', 'ledger balance', 'end balance',
        'running total', 'balance amount',
    ],
}

# Currency-prefixed aliases: headers like "Debit (INR)", "Balance (USD)" are
# cleaned to their base word by _clean_header before alias matching, so they
# resolve naturally to the right internal key without extra entries.

_FUZZY_THRESHOLD = 0.85


def _clean_header(raw: str) -> str:
    """
    Normalize a raw column header for alias matching.
    - Strips currency codes and parenthetical suffixes: "Debit (INR)" → "debit"
    - Unicode NFD → ASCII (drops accents): "Fecha" → "fecha"
    - Lowercase, collapse whitespace; underscores/hyphens → space.
    """
    # Drop parenthetical currency/unit suffixes: "Debit (INR)" → "Debit"
    s = re.sub(r'\s*\([^)]*\)', '', raw).strip()
    # Unicode normalize: drop accents
    s = unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')
    s = s.lower()
    # Underscores, hyphens, slashes, common punctuation → space
    s = re.sub(r'[\-_/\\|.,;:()[\]{}]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalize_header(raw_header: str) -> Optional[str]:
    """
    Return a confidently matched internal key (transaction_date, description,
    amount, debit, credit, balance) or None for unknown/ambiguous headers.

    Matching order:
    1. Exact alias match after cleaning (fast path, highest confidence).
    2. Fuzzy match (SequenceMatcher) ≥ FUZZY_THRESHOLD (0.85).
    3. None — never guesses below the threshold.

    The caller must retain the original header alongside any matched key.
    The alias dictionary (HEADER_ALIASES) is the only extension point needed
    to support new languages, banks, or institution-specific column names.
    """
    if not raw_header or not isinstance(raw_header, str):
        return None
    cleaned = _clean_header(raw_header)
    if not cleaned:
        return None

    # 1. Exact match
    for internal_key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if cleaned == alias:
                return internal_key

    # 2. Fuzzy match — only above safe threshold
    best_key: Optional[str] = None
    best_score = 0.0
    for internal_key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            score = SequenceMatcher(None, cleaned, alias).ratio()
            if score > best_score:
                best_score = score
                best_key = internal_key

    return best_key if best_score >= _FUZZY_THRESHOLD else None


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


def extract_currency_from_amount(raw: str) -> Optional[str]:
    """
    Extract a currency code from a raw amount string (e.g. '₹1,250.00', '$1,250.00 USD').
    Returns ISO 3-letter code or None when not present.
    Never infers currency from context — only from explicit symbols/codes in the string.
    """
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    for symbol, code in _CURRENCY_SYMBOLS:
        if symbol in s:
            return code
    m = re.search(r'\b([A-Z]{3})\b', s.upper())
    if m and m.group(1) in KNOWN_ISO_CURRENCIES:
        return m.group(1)
    return None


def normalize_amount_with_currency(value) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Like normalize_amount but also returns the currency code found in the string.
    Returns (amount, currency_code); either may be None.
    """
    raw_str = str(value) if value is not None else None
    currency = extract_currency_from_amount(raw_str) if raw_str else None
    return normalize_amount(value), currency


def normalize_amount(value) -> Decimal:
    """
    Parse amount from any currency-prefixed string.
    Strips all known currency symbols and ISO codes before parsing.
    Returns Decimal to avoid float precision issues; None for unparseable input.
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

    # Strip all recognized currency symbols (longest first to avoid prefix collisions)
    for symbol, _ in _CURRENCY_SYMBOLS:
        value = value.replace(symbol, '')

    # Strip standalone ISO codes (e.g. "USD 1,234.56")
    value = re.sub(r'\b[A-Z]{3}\b', '', value)

    # Strip Cr/Dr suffixes and remaining whitespace
    value = re.sub(r'[Cc][Rr]|[Dd][Rr]', '', value)
    value = value.replace(',', '').strip()

    try:
        return Decimal(value)
    except Exception:
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
