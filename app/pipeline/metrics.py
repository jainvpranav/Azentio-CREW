"""Compute financial metrics from transactions"""
from decimal import Decimal
from datetime import date
from collections import defaultdict
from sqlmodel import Session, select

from app.models import Transaction, Classification, TransactionCategory, Account


def compute_monthly_credits(session: Session, account_id: int) -> dict:
    """Compute total credits by month"""
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.credit != None)
    ).all()

    monthly = defaultdict(Decimal)
    for txn in transactions:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key] += txn.credit

    return {
        "metric": "monthly_credits",
        "account_id": account_id,
        "by_month": {k: float(v) for k, v in sorted(monthly.items())},
    }


def compute_monthly_debits(session: Session, account_id: int) -> dict:
    """Compute total debits by month"""
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.debit != None)
    ).all()

    monthly = defaultdict(Decimal)
    for txn in transactions:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key] += txn.debit

    return {
        "metric": "monthly_debits",
        "account_id": account_id,
        "by_month": {k: float(v) for k, v in sorted(monthly.items())},
    }


def compute_income(session: Session, account_id: int) -> dict:
    """
    Estimate income from SALARY and BUSINESS_RECEIPT transactions.
    Returns median monthly income if salaried.
    """
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.credit != None)
    ).all()

    monthly_income = defaultdict(Decimal)

    for txn in transactions:
        # Get current classification
        classification = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        if not classification:
            continue

        # Count only salary and business receipts
        if classification.category in [TransactionCategory.SALARY, TransactionCategory.BUSINESS_RECEIPT]:
            month_key = txn.txn_date.strftime("%Y-%m")
            monthly_income[month_key] += txn.credit

    if not monthly_income:
        return {
            "metric": "estimated_income",
            "account_id": account_id,
            "value": None,
            "by_month": {},
            "status": "no_income_found"
        }

    values = sorted(monthly_income.values())
    median = values[len(values) // 2] if values else Decimal(0)

    return {
        "metric": "estimated_income",
        "account_id": account_id,
        "value": float(median),
        "by_month": {k: float(v) for k, v in sorted(monthly_income.items())},
        "status": "calculated"
    }


def compute_recurring_obligations(session: Session, account_id: int) -> dict:
    """
    Find recurring debits: EMI, RENT, UTILITIES, etc.
    Returns sum of identified recurring debits per month.
    """
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.debit != None)
    ).all()

    recurring_debit = Decimal(0)

    for txn in transactions:
        classification = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        if not classification:
            continue

        # Count recurring categories
        if classification.category in [
            TransactionCategory.LOAN_EMI,
            TransactionCategory.RENT,
            TransactionCategory.UTILITIES,
            TransactionCategory.CARD_PAYMENT
        ]:
            recurring_debit += txn.debit

    # Rough estimate: divide by number of months
    months = len(set(t.txn_date.strftime("%Y-%m") for t in transactions))
    monthly_recurring = recurring_debit / months if months > 0 else Decimal(0)

    return {
        "metric": "recurring_obligations",
        "account_id": account_id,
        "estimated_monthly": float(monthly_recurring),
        "total_identified": float(recurring_debit),
    }


def compute_net_cashflow(session: Session, account_id: int) -> dict:
    """Net credits - debits by month"""
    credits = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.credit != None)
    ).all()

    debits = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.debit != None)
    ).all()

    monthly = defaultdict(lambda: [Decimal(0), Decimal(0)])  # [credits, debits]

    for txn in credits:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key][0] += txn.credit

    for txn in debits:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key][1] += txn.debit

    cashflow = {k: float(monthly[k][0] - monthly[k][1]) for k in monthly}

    return {
        "metric": "net_cashflow",
        "account_id": account_id,
        "by_month": dict(sorted(cashflow.items())),
    }


def get_all_metrics(session: Session, account_id: int) -> dict:
    """Compute all metrics for an account"""
    return {
        "account_id": account_id,
        "monthly_credits": compute_monthly_credits(session, account_id),
        "monthly_debits": compute_monthly_debits(session, account_id),
        "income": compute_income(session, account_id),
        "recurring_obligations": compute_recurring_obligations(session, account_id),
        "net_cashflow": compute_net_cashflow(session, account_id),
    }


# ===================== MetricResult-style breakdowns (traceable) =====================
# Every metric below returns {name, value, period, method, included[], excluded[], caveats[], by_month}
# so the UI can show exactly which transactions produced the number (BUILD_PLAN section 5).

EXCLUDE_FROM_INCOME = {
    TransactionCategory.INTERNAL_TRANSFER,
    TransactionCategory.REFUND,
    TransactionCategory.REVERSAL,
    TransactionCategory.LOAN_DISBURSEMENT,
}

EXCLUDE_FROM_DEBITS = {
    TransactionCategory.INTERNAL_TRANSFER,
    TransactionCategory.REVERSAL,
}

RECURRING_CATEGORIES = {
    TransactionCategory.LOAN_EMI,
    TransactionCategory.RENT,
    TransactionCategory.UTILITIES,
    TransactionCategory.CARD_PAYMENT,
}

METRIC_NAMES = [
    "monthly_credits_gross",
    "monthly_credits_adjusted",
    "monthly_debits_adjusted",
    "income",
    "recurring_obligations",
    "net_cashflow",
]


def _current_classification_map(session: Session, txns: list) -> dict:
    """txn_id -> current Classification (or None)"""
    result = {}
    for t in txns:
        c = session.exec(
            select(Classification)
            .where(Classification.txn_id == t.id)
            .where(Classification.is_current == True)
        ).first()
        result[t.id] = c
    return result


def _txn_ref(txn: Transaction, category, amount: Decimal) -> dict:
    return {
        "id": txn.id,
        "date": txn.txn_date.isoformat(),
        "description": txn.description,
        "amount": float(amount) if amount is not None else None,
        "category": category.value if category else "UNCLASSIFIED",
    }


def _coverage_caveats(session: Session, account_id: int):
    from app.pipeline.coverage import get_month_coverage

    coverage = get_month_coverage(session, account_id)
    grid = coverage["coverage_grid"]
    missing = [m for m, s in grid.items() if s == "missing"]
    partial = [m for m, s in grid.items() if s == "partial"]

    caveats = []
    if missing:
        caveats.append(f"Missing months (excluded, not counted as zero): {', '.join(missing)}")
    if partial:
        caveats.append(f"Partial statement coverage for: {', '.join(partial)}")

    return caveats, grid


def compute_metric_detail(session: Session, account_id: int, metric_name: str) -> dict:
    """Compute one metric with full included/excluded/caveats breakdown."""
    all_txns = session.exec(
        select(Transaction).where(Transaction.account_id == account_id)
    ).all()
    classifications = _current_classification_map(session, all_txns)
    caveats, coverage_grid = _coverage_caveats(session, account_id)

    included, excluded = [], []
    by_month = defaultdict(Decimal)
    value = None
    period = "all available months"
    method = ""

    def is_dup(t):
        return t.duplicate_of is not None

    if metric_name == "monthly_credits_gross":
        method = "Sum of all credit transactions, duplicates removed."
        for t in all_txns:
            if t.credit is None:
                continue
            cat = classifications[t.id].category if classifications[t.id] else None
            if is_dup(t):
                excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": "duplicate transaction"})
                continue
            included.append(_txn_ref(t, cat, t.credit))
            by_month[t.txn_date.strftime("%Y-%m")] += t.credit
        value = sum(by_month.values()) if by_month else Decimal(0)

    elif metric_name == "monthly_credits_adjusted":
        method = "Gross credits minus internal transfers, refunds, reversals and loan disbursements."
        for t in all_txns:
            if t.credit is None:
                continue
            cat = classifications[t.id].category if classifications[t.id] else None
            if is_dup(t):
                excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": "duplicate transaction"})
                continue
            if cat in EXCLUDE_FROM_INCOME:
                excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": f"classified as {cat.value}"})
                continue
            included.append(_txn_ref(t, cat, t.credit))
            by_month[t.txn_date.strftime("%Y-%m")] += t.credit
        value = sum(by_month.values()) if by_month else Decimal(0)

    elif metric_name == "monthly_debits_adjusted":
        method = "Gross debits minus internal transfers out and reversed debits."
        for t in all_txns:
            if t.debit is None:
                continue
            cat = classifications[t.id].category if classifications[t.id] else None
            if is_dup(t):
                excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "duplicate transaction"})
                continue
            if cat in EXCLUDE_FROM_DEBITS:
                excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": f"classified as {cat.value}"})
                continue
            included.append(_txn_ref(t, cat, t.debit))
            by_month[t.txn_date.strftime("%Y-%m")] += t.debit
        value = sum(by_month.values()) if by_month else Decimal(0)

    elif metric_name == "income":
        method = (
            "Median of monthly SALARY totals over available months (salaried), "
            "or median of monthly BUSINESS_RECEIPT totals (self-employed) when no salary cluster exists."
        )
        salary_found = any(
            classifications[t.id] and classifications[t.id].category == TransactionCategory.SALARY
            for t in all_txns
        )
        target_cat = TransactionCategory.SALARY if salary_found else TransactionCategory.BUSINESS_RECEIPT

        monthly = defaultdict(Decimal)
        for t in all_txns:
            if t.credit is None or is_dup(t):
                continue
            cls = classifications[t.id]
            cat = cls.category if cls else None
            if cat == target_cat:
                included.append(_txn_ref(t, cat, t.credit))
                monthly[t.txn_date.strftime("%Y-%m")] += t.credit
            else:
                excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": f"not {target_cat.value}"})

        by_month = monthly
        full_months = {m for m, s in coverage_grid.items() if s == "full"}
        values_for_median = sorted(v for m, v in monthly.items() if m in full_months) or sorted(monthly.values())
        value = values_for_median[len(values_for_median) // 2] if values_for_median else None

        period = f"profile: {'salaried' if salary_found else 'self-employed'}"
        if not monthly:
            caveats.append("No salary or business-receipt income found")

    elif metric_name == "recurring_obligations":
        method = "Sum of EMI + RENT + UTILITIES + CARD_PAYMENT debits, averaged across months observed."
        months_seen = set()
        for t in all_txns:
            if t.debit is None or is_dup(t):
                continue
            cls = classifications[t.id]
            cat = cls.category if cls else None
            months_seen.add(t.txn_date.strftime("%Y-%m"))
            if cat in RECURRING_CATEGORIES:
                included.append(_txn_ref(t, cat, t.debit))
                by_month[t.txn_date.strftime("%Y-%m")] += t.debit
            else:
                excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "not a recurring-obligation category"})
        total = sum(by_month.values()) if by_month else Decimal(0)
        value = (total / len(months_seen)) if months_seen else Decimal(0)
        period = "average per month"

    elif metric_name == "net_cashflow":
        method = "Adjusted credits minus adjusted debits, per month."
        credit_detail = compute_metric_detail(session, account_id, "monthly_credits_adjusted")
        debit_detail = compute_metric_detail(session, account_id, "monthly_debits_adjusted")
        months = set(credit_detail["by_month"]) | set(debit_detail["by_month"])
        for m in months:
            by_month[m] = Decimal(str(credit_detail["by_month"].get(m, 0))) - Decimal(str(debit_detail["by_month"].get(m, 0)))
        included = credit_detail["included"] + debit_detail["included"]
        excluded = credit_detail["excluded"] + debit_detail["excluded"]
        value = sum(by_month.values()) if by_month else Decimal(0)

    else:
        return {"error": f"unknown metric: {metric_name}"}

    return {
        "name": metric_name,
        "value": float(value) if value is not None else None,
        "period": period,
        "method": method,
        "included": included,
        "excluded": excluded,
        "caveats": caveats,
        "by_month": {k: float(v) for k, v in sorted(by_month.items())},
        "coverage_grid": coverage_grid,
    }


def get_metrics_summary(session: Session, account_id: int) -> dict:
    """Headline value + monthly series per metric, for cards + charts (no included/excluded payload)."""
    summary = {}
    for name in METRIC_NAMES:
        detail = compute_metric_detail(session, account_id, name)
        summary[name] = {
            "name": name,
            "value": detail.get("value"),
            "period": detail.get("period"),
            "by_month": detail.get("by_month", {}),
            "caveats": detail.get("caveats", []),
        }
    summary["coverage_grid"] = compute_metric_detail(session, account_id, "monthly_credits_gross").get("coverage_grid", {})
    return summary


def compute_balance_trend(session: Session, account_id: int) -> dict:
    """
    Month-end balance, minimum balance, and days below a threshold.
    Balance is carried forward from the last known transaction balance (never invented).
    """
    txns = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.balance != None)
        .order_by(Transaction.txn_date, Transaction.row_index)
    ).all()

    if not txns:
        return {"by_month": {}, "min_balance": None, "days_below_threshold": {}, "threshold": 1000}

    threshold = Decimal(1000)
    month_end_balance = {}
    for t in txns:
        month_end_balance[t.txn_date.strftime("%Y-%m")] = float(t.balance)

    min_balance = min(float(t.balance) for t in txns)

    # Carry-forward day count below threshold, per month
    days_below = defaultdict(int)
    for i in range(len(txns) - 1):
        start, bal = txns[i].txn_date, txns[i].balance
        end = txns[i + 1].txn_date
        d = start
        while d < end:
            if bal < threshold:
                days_below[d.strftime("%Y-%m")] += 1
            d = d.fromordinal(d.toordinal() + 1)

    return {
        "by_month": month_end_balance,
        "min_balance": min_balance,
        "days_below_threshold": dict(days_below),
        "threshold": float(threshold),
    }
