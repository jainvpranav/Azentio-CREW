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
