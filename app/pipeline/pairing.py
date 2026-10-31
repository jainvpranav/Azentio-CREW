"""
Pairing logic: reversals, refunds, cross-account transfers, and recurring
(salary / EMI) clusters. Runs BEFORE keyword classification because pairing
outcomes override keyword guesses (BUILD_PLAN.md section 4).

Each finder returns a plain dict keyed by txn_id so classify.py can look up
a transaction's pairing outcome in O(1) without re-querying the DB.
"""
from collections import defaultdict
from decimal import Decimal
from sqlmodel import Session, select

from app.models import Transaction, Account

REV_KEYWORDS = ["REV", "REVERSAL", "RETURN", "REVERSED"]
REFUND_KEYWORDS = ["REFUND", "RFND", "CASHBACK", "CHARGEBACK"]
SALARY_KEYWORDS = ["SAL", "SALARY", "PAYROLL"]
STOPWORDS = {"THE", "TO", "FROM", "AND", "FOR"}

# A recurring same-amount monthly debit to these is clearly NOT a loan EMI,
# even though it matches EMI_RECUR's amount+timing pattern (e.g. a fixed
# monthly electricity bill) - those keyword rules take priority.
NON_EMI_KEYWORDS = [
    "BESCOM", "ELECTRICITY", "WATER", "GAS", "AIRTEL", "JIO", "BSNL", "ACT", "BROADBAND", "DTH",
    "RENT", "CCPAYMENT", "CREDITCARD", "CARDDUE",
]


def _normalize(text: str) -> str:
    return text.upper().replace(" ", "").replace("-", "").replace("/", "").replace(".", "")


def _desc_tokens(text: str) -> set:
    cleaned = "".join(c if c.isalnum() else " " for c in text.upper())
    return {w for w in cleaned.split() if len(w) > 1 and w not in STOPWORDS and not w.isdigit()}


def _token_overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_reversal_pairs(txns: list) -> dict:
    """
    Rule 1 REV_PAIR: credit & debit of the same amount, within 7 days, one
    side carries a reversal keyword. Only the keyword side is marked
    REVERSAL; the original keeps its own classification.
    Returns {txn_id: {"original_id": int, "reason": str}}
    """
    result = {}
    used_as_original = set()

    for t in txns:
        if not any(kw in t.description.upper() for kw in REV_KEYWORDS):
            continue
        amt = t.credit or t.debit
        if amt is None:
            continue

        best = None
        for other in txns:
            if other.id == t.id or other.id in used_as_original:
                continue
            other_amt = other.credit or other.debit
            if other_amt != amt:
                continue
            if bool(other.credit) == bool(t.credit):
                continue  # must be opposite sides
            if abs((t.txn_date - other.txn_date).days) > 7:
                continue
            best = other
            break

        if best:
            used_as_original.add(best.id)
            result[t.id] = {
                "original_id": best.id,
                "reason": f"Reversal of txn #{best.id} on {best.txn_date} for ₹{amt}",
            }

    return result


def find_refund_pairs(txns: list) -> dict:
    """
    Rule 2 REFUND_KW: credit with a refund keyword, paired with the best
    matching earlier debit (by description token overlap) within 45 days.
    Returns {txn_id: {"original_id": int|None, "merchant": str|None, "reason": str}}
    """
    result = {}
    debits = [t for t in txns if t.debit is not None]

    for t in txns:
        if t.credit is None:
            continue
        if not any(kw in t.description.upper() for kw in REFUND_KEYWORDS):
            continue

        t_tokens = _desc_tokens(t.description) - {"REFUND", "RFND", "CASHBACK", "CHARGEBACK"}
        best, best_overlap = None, 0.0
        for d in debits:
            if d.txn_date > t.txn_date or (t.txn_date - d.txn_date).days > 45:
                continue
            overlap = _token_overlap(t_tokens, _desc_tokens(d.description))
            if overlap > best_overlap:
                best, best_overlap = d, overlap

        if best and best_overlap >= 0.3:
            result[t.id] = {
                "original_id": best.id,
                "merchant": best.description,
                "reason": f"Refund from {best.description}; paired with #{best.id}",
            }
        else:
            result[t.id] = {
                "original_id": None,
                "merchant": None,
                "reason": "Refund keyword, no original found",
            }

    return result


def find_cross_account_transfer_pairs(session: Session) -> dict:
    """
    Rule 3 XFER_PAIR: debit in account A matched to a credit of the same
    amount (±1 day) in a different uploaded account. Both legs are marked
    INTERNAL_TRANSFER since both sides should be excluded from income/expense.
    Returns {txn_id: {"pair_id": int, "reason": str}}
    """
    accounts = {a.id: a for a in session.exec(select(Account)).all()}
    all_txns = session.exec(select(Transaction)).all()

    by_account = defaultdict(list)
    for t in all_txns:
        by_account[t.account_id].append(t)

    result = {}
    used = set()
    account_ids = list(by_account.keys())

    for acc_a in account_ids:
        for acc_b in account_ids:
            if acc_a == acc_b:
                continue
            for debit_txn in by_account[acc_a]:
                if debit_txn.debit is None or debit_txn.id in used:
                    continue
                for credit_txn in by_account[acc_b]:
                    if credit_txn.credit is None or credit_txn.id in used:
                        continue
                    if credit_txn.credit != debit_txn.debit:
                        continue
                    if abs((credit_txn.txn_date - debit_txn.txn_date).days) > 1:
                        continue

                    last4_b = str(accounts[acc_b].account_number)[-4:]
                    last4_a = str(accounts[acc_a].account_number)[-4:]
                    result[debit_txn.id] = {
                        "pair_id": credit_txn.id,
                        "reason": f"Matched to credit #{credit_txn.id} in your account XXXX{last4_b}",
                    }
                    result[credit_txn.id] = {
                        "pair_id": debit_txn.id,
                        "reason": f"Matched to debit #{debit_txn.id} in your account XXXX{last4_a}",
                    }
                    used.add(debit_txn.id)
                    used.add(credit_txn.id)
                    break

    return result


def find_salary_clusters(credit_txns: list) -> dict:
    """
    Rule 7 SALARY_RECUR: recurring monthly credit cluster (gap 25-35 days,
    amount within ±15% of cluster median, >=2 occurrences), AND (salary
    keyword present OR consistent day-of-month ±3). Clusters are built on
    amount + timing, not description, so a payroll-provider rename stays in
    one cluster.
    Returns {txn_id: {"n": int, "median": Decimal, "day": int, "variants": [str]}}
    """
    candidates = sorted(credit_txns, key=lambda t: t.txn_date)
    assigned = set()
    clusters = []

    for i, seed in enumerate(candidates):
        if seed.id in assigned or seed.credit is None:
            continue
        cluster = [seed]
        last = seed
        for t in candidates[i + 1:]:
            if t.id in assigned or t.credit is None:
                continue
            gap = (t.txn_date - last.txn_date).days
            if gap < 25 or gap > 35:
                continue
            median = sorted(x.credit for x in cluster)[len(cluster) // 2]
            if median == 0 or abs(t.credit - median) / median > Decimal("0.15"):
                continue
            cluster.append(t)
            last = t
        if len(cluster) >= 2:
            clusters.append(cluster)
            assigned.update(t.id for t in cluster)

    result = {}
    for cluster in clusters:
        amounts = sorted(t.credit for t in cluster)
        median = amounts[len(amounts) // 2]
        days = [t.txn_date.day for t in cluster]
        day_mode = max(set(days), key=days.count)
        day_consistent = all(abs(d - day_mode) <= 3 for d in days)
        has_keyword = any(any(kw in t.description.upper() for kw in SALARY_KEYWORDS) for t in cluster)

        if not (has_keyword or day_consistent):
            continue

        variants = sorted({t.description for t in cluster})
        for t in cluster:
            result[t.id] = {"n": len(cluster), "median": median, "day": day_mode, "variants": variants}

    return result


def find_emi_clusters(debit_txns: list) -> dict:
    """
    Rule 8 EMI_RECUR: same amount (±1%) debit, monthly (gap 25-35 days),
    to a consistent counterparty (description token overlap).
    Returns {txn_id: {"n": int, "amount": Decimal, "counterparty": str}}
    """
    candidates = sorted(
        (t for t in debit_txns if not any(kw in _normalize(t.description) for kw in NON_EMI_KEYWORDS)),
        key=lambda t: t.txn_date,
    )
    assigned = set()
    clusters = []

    for i, seed in enumerate(candidates):
        if seed.id in assigned or seed.debit is None:
            continue
        cluster = [seed]
        last = seed
        seed_tokens = _desc_tokens(seed.description)
        for t in candidates[i + 1:]:
            if t.id in assigned or t.debit is None:
                continue
            gap = (t.txn_date - last.txn_date).days
            if gap < 25 or gap > 35:
                continue
            if last.debit == 0 or abs(t.debit - last.debit) / last.debit > Decimal("0.01"):
                continue
            if _token_overlap(seed_tokens, _desc_tokens(t.description)) < 0.4:
                continue
            cluster.append(t)
            last = t
        if len(cluster) >= 2:
            clusters.append(cluster)
            assigned.update(t.id for t in cluster)

    result = {}
    for cluster in clusters:
        for t in cluster:
            result[t.id] = {"n": len(cluster), "amount": t.debit, "counterparty": cluster[0].description}

    return result
