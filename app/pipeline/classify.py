"""Deterministic classification rules engine"""
from datetime import datetime, timedelta
from decimal import Decimal
from sqlmodel import Session, select

from app.models import Transaction, TransactionCategory, Classification


class ClassificationResult:
    def __init__(self, category: TransactionCategory, rule_id: str, reason: str, confidence: float = 1.0):
        self.category = category
        self.rule_id = rule_id
        self.reason = reason
        self.confidence = confidence


def normalize_desc(text: str) -> str:
    """Normalize description for rule matching"""
    return text.upper().replace(" ", "").replace("-", "")


def classify_transaction(session: Session, txn: Transaction) -> ClassificationResult:
    """
    Apply ordered rules to classify a transaction.
    First match wins. Rules follow BUILD_PLAN.md specification.

    Returns:
        ClassificationResult with category, rule_id, reason, confidence
    """
    desc = normalize_desc(txn.description)
    amount = txn.credit or txn.debit
    is_credit = bool(txn.credit)

    # Rule 1: REVERSAL_PAIR - same amount credit+debit within 7 days
    # (Simplified for MVP, would need account-wide pairing logic)
    if "REV" in desc or "REVERSAL" in desc or "RETURN" in desc:
        if not is_credit:
            return ClassificationResult(
                TransactionCategory.REVERSAL,
                "REV_MANUAL",
                "Reversal keyword detected",
                0.9
            )

    # Rule 2: REFUND
    if is_credit and ("REFUND" in desc or "RFND" in desc or "CASHBACK" in desc):
        return ClassificationResult(
            TransactionCategory.REFUND,
            "REFUND_KW",
            "Refund keyword detected",
            0.9
        )

    # Rule 3-4: INTERNAL_TRANSFER (counterparty = holder or SELF/OWN A/C)
    if "SELF" in desc or "OWNACC" in desc or "SWEEP" in desc or "FD" in desc:
        if is_credit:
            return ClassificationResult(
                TransactionCategory.INTERNAL_TRANSFER,
                "XFER_SELF",
                "Internal transfer (counterparty is self)",
                0.95
            )

    # Rule 5: LOAN_DISBURSEMENT
    if is_credit and ("LOANDISB" in desc or "DISBURSAL" in desc or "LOANACC" in desc):
        return ClassificationResult(
            TransactionCategory.LOAN_DISBURSEMENT,
            "LOAN_DISB",
            "Loan disbursement detected",
            0.95
        )

    # Rule 6: RETURNED_PAYMENT
    if "RETURN" in desc or "BOUNCE" in desc or "INSUFF" in desc or "ECSRTN" in desc or "NACHRTN" in desc:
        if not is_credit:
            return ClassificationResult(
                TransactionCategory.RETURNED_PAYMENT,
                "RETURNED",
                "Returned payment / bounce detected",
                0.9
            )

    # Rule 7: SALARY (simplified - keyword only)
    if is_credit and ("SAL" in desc or "SALARY" in desc or "PAYROLL" in desc):
        return ClassificationResult(
            TransactionCategory.SALARY,
            "SALARY_KW",
            "Salary keyword detected",
            0.85
        )

    # Rule 8: EMI (recurring loan payment)
    if not is_credit and ("EMI" in desc or "NACH" in desc or "ECS" in desc or "LOAN" in desc or "ACHD" in desc):
        return ClassificationResult(
            TransactionCategory.LOAN_EMI,
            "EMI_KW",
            "EMI/recurring loan payment detected",
            0.85
        )

    # Rule 9: RENT
    if "RENT" in desc:
        return ClassificationResult(
            TransactionCategory.RENT,
            "RENT_KW",
            "Rent keyword detected",
            0.9
        )

    # Rule 10: UTILITIES
    utilities = ["BESCOM", "ELECTRICITY", "WATER", "GAS", "AIRTEL", "JIO", "BSNL", "ACT", "BROADBAND", "DTH"]
    if any(util in desc for util in utilities):
        return ClassificationResult(
            TransactionCategory.UTILITIES,
            "UTILITIES_KW",
            "Utility provider detected",
            0.95
        )

    # Rule 11: CARD_PAYMENT
    if not is_credit and ("CCPAYMENT" in desc or "CREDITCARD" in desc or "CARDDUE" in desc):
        return ClassificationResult(
            TransactionCategory.CARD_PAYMENT,
            "CARD_PAY",
            "Credit card payment detected",
            0.95
        )

    # Rule 12: CASH_DEPOSIT / CASH_WITHDRAWAL
    if is_credit and ("CASHDEP" in desc or "CDM" in desc or "BYCASH" in desc):
        return ClassificationResult(
            TransactionCategory.CASH_DEPOSIT,
            "CASH_DEP",
            "Cash deposit detected",
            0.9
        )

    if not is_credit and ("ATM" in desc or "CASHWDL" in desc):
        return ClassificationResult(
            TransactionCategory.CASH_WITHDRAWAL,
            "CASH_WDL",
            "Cash withdrawal detected",
            0.9
        )

    # Rule 13: CHARGES / INTEREST
    if "CHGS" in desc or "FEE" in desc or "GSTON" in desc:
        return ClassificationResult(
            TransactionCategory.BANK_CHARGES,
            "CHARGES",
            "Bank charges/fees detected",
            0.85
        )

    if "INTPD" in desc or "INTEREST" in desc:
        return ClassificationResult(
            TransactionCategory.INTEREST,
            "INTEREST",
            "Interest detected",
            0.9
        )

    # Rule 14: BUSINESS_RECEIPT (remaining credits)
    if is_credit:
        if "UPI" in desc or "NEFT" in desc or "IMPS" in desc or "RTGS" in desc:
            return ClassificationResult(
                TransactionCategory.BUSINESS_RECEIPT,
                "BIZ_RECEIPT",
                "Third-party credit via payment gateway",
                0.8
            )

    # Rule 15: OTHER_EXPENSE (remaining debits)
    if not is_credit:
        return ClassificationResult(
            TransactionCategory.OTHER_EXPENSE,
            "OTHER_EXP",
            "Unclassified expense",
            0.5
        )

    # Default: UNCLASSIFIED
    return ClassificationResult(
        TransactionCategory.UNCLASSIFIED,
        "UNCLASSIFIED",
        "No matching rule",
        0.0
    )


def classify_all_transactions(session: Session) -> dict:
    """
    Classify all unclassified transactions.
    Creates Classification records (append-only).

    Returns:
        {
            "total_classified": int,
            "by_category": {...}
        }
    """
    # Get all transactions without current classification
    transactions = session.exec(select(Transaction)).all()

    counts_by_category = {}
    classified_count = 0

    for txn in transactions:
        # Check if already classified
        existing = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        if existing:
            # Already classified
            cat = existing.category
            counts_by_category[cat] = counts_by_category.get(cat, 0) + 1
            continue

        # Apply rules
        result = classify_transaction(session, txn)

        # Create classification record
        classification = Classification(
            txn_id=txn.id,
            category=result.category,
            rule_id=result.rule_id,
            reason=result.reason,
            confidence=result.confidence,
            source="rule",
            is_current=True,
        )
        session.add(classification)
        classified_count += 1

        cat = result.category
        counts_by_category[cat] = counts_by_category.get(cat, 0) + 1

    session.commit()

    return {
        "total_classified": classified_count,
        "by_category": dict(counts_by_category),
    }
