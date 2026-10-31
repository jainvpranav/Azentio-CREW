"""Deterministic classification rules engine"""
from collections import defaultdict
from sqlmodel import Session, select

from app.models import Transaction, TransactionCategory, Classification, Account
from app.pipeline.pairing import (
    find_reversal_pairs,
    find_refund_pairs,
    find_cross_account_transfer_pairs,
    find_salary_clusters,
    find_emi_clusters,
)


class ClassificationResult:
    def __init__(self, category: TransactionCategory, rule_id: str, reason: str, confidence: float = 1.0):
        self.category = category
        self.rule_id = rule_id
        self.reason = reason
        self.confidence = confidence


def normalize_desc(text: str) -> str:
    """Normalize description for rule matching"""
    return text.upper().replace(" ", "").replace("-", "").replace("/", "").replace(".", "")


def _self_transfer_match(txn: Transaction, holder_name: str) -> bool:
    desc = normalize_desc(txn.description)
    if "SELF" in desc or "OWNAC" in desc or "SWEEP" in desc or "FD" in desc:
        return True
    if not holder_name or holder_name.upper() == "UNKNOWN":
        return False
    holder_tokens = {w for w in holder_name.upper().split() if len(w) > 1}
    if not holder_tokens:
        return False
    desc_tokens = {w for w in txn.description.upper().replace("-", " ").split() if len(w) > 1}
    overlap = len(holder_tokens & desc_tokens) / len(holder_tokens)
    return overlap >= 0.8


def classify_transaction(txn: Transaction, ctx: dict, xfer_pairs: dict) -> ClassificationResult:
    """
    Apply ordered rules to classify a transaction. First match wins.
    Pairing outcomes (ctx, xfer_pairs - computed once per account/globally
    by classify_all_transactions) take priority over keyword guesses, per
    BUILD_PLAN.md section 4.
    """
    desc = normalize_desc(txn.description)
    is_credit = bool(txn.credit)

    # Rule 1: REV_PAIR
    rev = ctx["reversal_pairs"].get(txn.id)
    if rev:
        return ClassificationResult(TransactionCategory.REVERSAL, "REV_PAIR", rev["reason"], 0.95)

    # Rule 2: REFUND_KW
    refund = ctx["refund_pairs"].get(txn.id)
    if refund:
        return ClassificationResult(TransactionCategory.REFUND, "REFUND_KW", refund["reason"], 0.9)

    # Rule 3: XFER_PAIR (cross-account, both legs)
    xfer = xfer_pairs.get(txn.id)
    if xfer:
        return ClassificationResult(TransactionCategory.INTERNAL_TRANSFER, "XFER_PAIR", xfer["reason"], 0.95)

    # Rule 4: XFER_SELF
    if _self_transfer_match(txn, ctx.get("holder_name")):
        return ClassificationResult(
            TransactionCategory.INTERNAL_TRANSFER,
            "XFER_SELF",
            "Counterparty matches account holder name",
            0.9,
        )

    # Rule 5: LOAN_DISBURSEMENT
    if is_credit and ("LOANDISB" in desc or "DISBURSAL" in desc or "LOANACC" in desc):
        return ClassificationResult(TransactionCategory.LOAN_DISBURSEMENT, "LOAN_DISB", "Loan disbursement detected", 0.95)

    # Rule 6: RETURNED_PAYMENT
    if not is_credit and ("RETURN" in desc or "BOUNCE" in desc or "INSUFF" in desc or "ECSRTN" in desc or "NACHRTN" in desc):
        return ClassificationResult(TransactionCategory.RETURNED_PAYMENT, "RETURNED", "Returned payment / bounce detected", 0.9)

    # Rule 7: SALARY_RECUR
    salary = ctx["salary_clusters"].get(txn.id)
    if salary:
        variants = ", ".join(salary["variants"])
        reason = f"Recurring monthly credit (n={salary['n']}, ~₹{salary['median']}, day {salary['day']}); description varies: {variants}"
        return ClassificationResult(TransactionCategory.SALARY, "SALARY_RECUR", reason, 0.9)

    # Fallback keyword salary (single observation, no cluster yet)
    if is_credit and ("SAL" in desc or "SALARY" in desc or "PAYROLL" in desc):
        return ClassificationResult(TransactionCategory.SALARY, "SALARY_KW", "Salary keyword detected", 0.7)

    # Rule 8: EMI_RECUR
    emi = ctx["emi_clusters"].get(txn.id)
    if emi:
        reason = f"Recurring ₹{emi['amount']} debit monthly to {emi['counterparty']}"
        return ClassificationResult(TransactionCategory.LOAN_EMI, "EMI_RECUR", reason, 0.9)

    if not is_credit and ("EMI" in desc or "NACH" in desc or "ECS" in desc or "LOAN" in desc or "ACHD" in desc):
        return ClassificationResult(TransactionCategory.LOAN_EMI, "EMI_KW", "EMI/recurring loan payment detected", 0.85)

    # Rule 9: RENT
    if "RENT" in desc:
        return ClassificationResult(TransactionCategory.RENT, "RENT_KW", "Rent keyword detected", 0.9)

    # Rule 10: UTILITIES
    utilities = ["BESCOM", "ELECTRICITY", "WATER", "GAS", "AIRTEL", "JIO", "BSNL", "ACT", "BROADBAND", "DTH"]
    if any(util in desc for util in utilities):
        return ClassificationResult(TransactionCategory.UTILITIES, "UTILITIES_KW", "Utility provider detected", 0.95)

    # Rule 11: CARD_PAYMENT
    if not is_credit and ("CCPAYMENT" in desc or "CREDITCARD" in desc or "CARDDUE" in desc):
        return ClassificationResult(TransactionCategory.CARD_PAYMENT, "CARD_PAY", "Credit card payment detected", 0.95)

    # Rule 12: CASH_DEPOSIT / CASH_WITHDRAWAL
    if is_credit and ("CASHDEP" in desc or "CDM" in desc or "BYCASH" in desc):
        return ClassificationResult(TransactionCategory.CASH_DEPOSIT, "CASH_DEP", "Cash deposit detected", 0.9)

    if not is_credit and ("ATM" in desc or "CASHWDL" in desc):
        return ClassificationResult(TransactionCategory.CASH_WITHDRAWAL, "CASH_WDL", "Cash withdrawal detected", 0.9)

    # Rule 13: CHARGES / INTEREST
    if "CHGS" in desc or "FEE" in desc or "GSTON" in desc:
        return ClassificationResult(TransactionCategory.BANK_CHARGES, "CHARGES", "Bank charges/fees detected", 0.85)

    if "INTPD" in desc or "INTEREST" in desc:
        return ClassificationResult(TransactionCategory.INTEREST, "INTEREST", "Interest detected", 0.9)

    # Rule 14: BUSINESS_RECEIPT (remaining credits)
    if is_credit:
        if "UPI" in desc or "NEFT" in desc or "IMPS" in desc or "RTGS" in desc:
            return ClassificationResult(
                TransactionCategory.BUSINESS_RECEIPT,
                "BIZ_RECEIPT",
                "Third-party credit via payment gateway, not salary/transfer/refund",
                0.8,
            )

    # Rule 15: OTHER_EXPENSE (remaining debits)
    if not is_credit:
        return ClassificationResult(TransactionCategory.OTHER_EXPENSE, "OTHER_EXP", "Unclassified expense", 0.5)

    # Default: UNCLASSIFIED
    return ClassificationResult(TransactionCategory.UNCLASSIFIED, "UNCLASSIFIED", "No matching rule", 0.0)


def classify_all_transactions(session: Session) -> dict:
    """
    Classify all unclassified transactions. Pairing (reversals, refunds,
    cross-account transfers, salary/EMI clustering) runs once per account
    before any keyword rule is applied. Creates Classification records
    (append-only).

    Returns:
        {"total_classified": int, "by_category": {...}}
    """
    transactions = session.exec(select(Transaction)).all()

    by_account = defaultdict(list)
    for t in transactions:
        by_account[t.account_id].append(t)

    accounts = {a.id: a for a in session.exec(select(Account)).all()}
    xfer_pairs = find_cross_account_transfer_pairs(session)

    context_by_account = {}
    for account_id, txns in by_account.items():
        credits = [t for t in txns if t.credit is not None]
        debits = [t for t in txns if t.debit is not None]
        context_by_account[account_id] = {
            "reversal_pairs": find_reversal_pairs(txns),
            "refund_pairs": find_refund_pairs(txns),
            "salary_clusters": find_salary_clusters(credits),
            "emi_clusters": find_emi_clusters(debits),
            "holder_name": accounts[account_id].holder_name if account_id in accounts else None,
        }

    counts_by_category = {}
    classified_count = 0

    for txn in transactions:
        existing = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        if existing:
            cat = existing.category
            counts_by_category[cat] = counts_by_category.get(cat, 0) + 1
            continue

        ctx = context_by_account[txn.account_id]
        result = classify_transaction(txn, ctx, xfer_pairs)

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
