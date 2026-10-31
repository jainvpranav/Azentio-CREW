"""
Individual borrower metrics (handoff Phase 2): VNMI, NAMB, FOIR/DTI,
Salary-to-Obligation Cleansing Cycle, Discretionary Spending Ratio.

Every function returns the same MetricResult-style dict used in
app/pipeline/metrics.py (value, period, method, included, excluded,
caveats) so the UI drill-down and audit trail work identically for these
new metrics. None of these invent a number when data is missing - they
return value=None (or a NOT_AVAILABLE-style status) with a caveat naming
what's missing.
"""
from decimal import Decimal
from collections import defaultdict
from datetime import timedelta
from sqlmodel import Session, select

from app.models import Transaction, TransactionCategory
from app.pipeline.metrics import _current_classification_map, _txn_ref, _coverage_caveats
from app.pipeline.categories import is_discretionary
from app.config import thresholds as cfg

EMI_LIKE_DEBT_CATEGORIES = {TransactionCategory.LOAN_EMI, TransactionCategory.CARD_PAYMENT}


def _all_txns(session: Session, account_id: int) -> list:
    return session.exec(select(Transaction).where(Transaction.account_id == account_id)).all()


def compute_vnmi(session: Session, account_id: int) -> dict:
    """
    Verified Net Monthly Income: average monthly SALARY credits over full
    coverage months. A month whose salary is >=1.5x the trailing median is
    treated as containing an exceptional bonus and excluded from the
    average (reported separately), per handoff: "a raise or bonus must not
    automatically invalidate salary classification" / "distinguish regular
    income from exceptional bonuses where possible".
    """
    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, coverage_grid = _coverage_caveats(session, account_id)
    full_months = {m for m, s in coverage_grid.items() if s == "full"}

    included, excluded = [], []
    monthly = defaultdict(Decimal)
    for t in txns:
        if t.credit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        if cat == TransactionCategory.SALARY:
            included.append(_txn_ref(t, cat, t.credit))
            monthly[t.txn_date.strftime("%Y-%m")] += t.credit
        elif cat in (TransactionCategory.BUSINESS_RECEIPT, TransactionCategory.POSSIBLE_BUSINESS_RECEIPT,
                     TransactionCategory.UNVERIFIED_CREDIT, TransactionCategory.INTERNAL_TRANSFER,
                     TransactionCategory.REFUND, TransactionCategory.REVERSAL, TransactionCategory.LOAN_DISBURSEMENT):
            excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": f"not verified primary income ({cat.value})"})

    if not monthly:
        return {
            "name": "vnmi", "value": None, "period": None,
            "method": "Average of monthly SALARY credits over full coverage months.",
            "included": [], "excluded": excluded,
            "caveats": caveats + ["No SALARY-classified income found; VNMI not computable."],
            "by_month": {}, "bonus_months_excluded": [],
        }

    # restrict to full months where possible, fall back to whatever exists
    scored_months = {m: v for m, v in monthly.items() if m in full_months} or dict(monthly)
    sorted_vals = sorted(scored_months.values())
    median = sorted_vals[len(sorted_vals) // 2]

    regular_months = {}
    bonus_months = {}
    for m, v in scored_months.items():
        if median > 0 and v >= median * Decimal("1.5"):
            bonus_months[m] = v
        else:
            regular_months[m] = v

    base = regular_months or scored_months
    vnmi = sum(base.values()) / len(base)

    extra_caveats = list(caveats)
    if bonus_months:
        extra_caveats.append(
            f"Excluded from average as likely bonus/exceptional (>=1.5x median): {', '.join(sorted(bonus_months))}"
        )
    if len(scored_months) < cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION:
        extra_caveats.append("Fewer than 2 full months of salary history - VNMI is provisional.")

    return {
        "name": "vnmi",
        "value": float(vnmi),
        "period": f"average over {len(base)} month(s)",
        "method": "Average of monthly SALARY credits over full coverage months, excluding likely-bonus months (>=1.5x median).",
        "included": included,
        "excluded": excluded,
        "caveats": extra_caveats,
        "by_month": {k: float(v) for k, v in sorted(monthly.items())},
        "bonus_months_excluded": sorted(bonus_months.keys()),
    }


def compute_namb(session: Session, account_id: int, period_months: int = None) -> dict:
    """
    Net Average Monthly Balance: sum of daily closing balances / number of
    days, reconstructed from the transaction balance trail. Only computed
    when at least one statement for the account reconciled (opening + txns
    == closing) - otherwise the balance trail isn't trustworthy enough to
    treat as "the" daily balance, and this returns None with that caveat
    labelled explicitly as an approximation gap, not a silent guess.
    Per-account only (see ASSUMPTIONS.md A-002 for consolidated accounts).
    """
    from app.models import Statement

    statements = session.exec(select(Statement).where(Statement.account_id == account_id)).all()
    any_reconciled = any(s.reconciled for s in statements)

    txns = sorted(
        (t for t in _all_txns(session, account_id) if t.balance is not None and t.duplicate_of is None),
        key=lambda t: (t.txn_date, t.row_index),
    )
    if not txns:
        return {
            "name": "namb", "value": None, "period": None,
            "method": "Sum of daily closing balances / number of days (per account).",
            "included": [], "excluded": [],
            "caveats": ["No balance data available."], "by_month": {},
        }

    caveats = []
    if not any_reconciled:
        caveats.append(
            "No statement for this account reconciled cleanly (opening + txns = closing); "
            "daily balance reconstruction is an approximation and may be unreliable."
        )

    day_balance = {}
    for i in range(len(txns)):
        d = txns[i].txn_date
        day_balance[d] = txns[i].balance  # last txn of the day wins (list is date-ordered)

    days = sorted(day_balance.keys())
    total_days = (days[-1] - days[0]).days + 1
    if total_days <= 0:
        total_days = 1

    running_sum = Decimal(0)
    current_balance = day_balance[days[0]]
    d = days[0]
    idx = 0
    while d <= days[-1]:
        if d in day_balance:
            current_balance = day_balance[d]
        running_sum += current_balance
        d += timedelta(days=1)

    namb = running_sum / total_days
    by_month = defaultdict(list)
    for d2, bal in day_balance.items():
        by_month[d2.strftime("%Y-%m")].append(float(bal))
    month_avg = {m: round(sum(v) / len(v), 2) for m, v in sorted(by_month.items())}

    return {
        "name": "namb",
        "value": float(namb),
        "period": f"{days[0].isoformat()} to {days[-1].isoformat()} ({total_days} days)",
        "method": "Average daily closing balance: balance carried forward from the last known transaction each day, summed over the period and divided by days. Per account (not consolidated across linked accounts).",
        "included": [_txn_ref(t, None, t.balance) for t in txns],
        "excluded": [],
        "caveats": caveats,
        "by_month": month_avg,
    }


def compute_foir(session: Session, account_id: int) -> dict:
    """
    FOIR / DTI = (Monthly fixed debt obligations / VNMI) * 100.
    Debt obligations = LOAN_EMI + CARD_PAYMENT (revolving debt bill
    payments) debits, averaged per month observed. RENT/UTILITIES are
    fixed obligations but not debt, so excluded here (see DECISIONS.md).
    Card *purchases* aren't tracked (ASSUMPTIONS.md A-004: no card
    statement ingestion), so there is no double-counting of card spend vs
    card bill payment to guard against in this build - disclosed as a
    limitation instead of silently assumed correct.
    """
    vnmi_result = compute_vnmi(session, account_id)
    vnmi = vnmi_result["value"]

    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, coverage_grid = _coverage_caveats(session, account_id)
    full_months = {m for m, s in coverage_grid.items() if s == "full"}

    included, excluded = [], []
    monthly = defaultdict(Decimal)
    months_seen = set()
    for t in txns:
        if t.debit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        month_key = t.txn_date.strftime("%Y-%m")
        months_seen.add(month_key)
        if cat in EMI_LIKE_DEBT_CATEGORIES:
            included.append(_txn_ref(t, cat, t.debit))
            monthly[month_key] += t.debit
        else:
            excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "not an identifiable debt obligation (EMI/card payment)"})

    scored_months = {m: v for m, v in monthly.items() if m in full_months} or dict(monthly)
    monthly_obligation = (sum(scored_months.values()) / len(scored_months)) if scored_months else Decimal(0)

    extra_caveats = list(caveats)
    extra_caveats.append("Card purchases are not separately tracked (bank statement only); only card bill payments are counted as obligations.")

    if vnmi is None or vnmi == 0:
        return {
            "name": "foir", "value": None, "period": "average per month",
            "method": "(Monthly fixed debt obligations / VNMI) * 100. Obligations = LOAN_EMI + CARD_PAYMENT debits.",
            "included": included, "excluded": excluded,
            "caveats": extra_caveats + ["VNMI not computable - FOIR requires verified income."],
            "monthly_obligation": float(monthly_obligation), "band": "NOT_AVAILABLE",
        }

    foir = (monthly_obligation / Decimal(str(vnmi))) * 100

    if foir <= cfg.FOIR_LOWER_BURDEN_MAX:
        band = "lower_burden"
    elif foir <= cfg.FOIR_ELEVATED_MAX:
        band = "elevated"
    else:
        band = "higher_burden"

    return {
        "name": "foir",
        "value": float(foir),
        "period": "average per month",
        "method": "(Monthly fixed debt obligations / VNMI) * 100. Obligations = LOAN_EMI + CARD_PAYMENT debits, averaged per month.",
        "included": included,
        "excluded": excluded,
        "caveats": extra_caveats,
        "monthly_obligation": float(monthly_obligation),
        "vnmi_used": vnmi,
        "band": band,
        "band_thresholds": {"lower_burden_max": float(cfg.FOIR_LOWER_BURDEN_MAX), "elevated_max": float(cfg.FOIR_ELEVATED_MAX)},
    }


def compute_salary_to_obligation_cleansing_cycle(session: Session, account_id: int,
                                                   low_balance_threshold: Decimal = None) -> dict:
    """
    Days from each salary credit to (a) clearance of that month's recurring
    obligations (EMI/rent debits on/after the salary date) and (b) the
    first day the running balance falls below a configurable low-balance
    threshold. A low balance alone is reported as a fact, not treated as
    proof of distress (handoff instruction).
    """
    threshold = low_balance_threshold or cfg.LOW_BALANCE_THRESHOLD_FOR_CLEANSING_CYCLE
    txns = sorted(_all_txns(session, account_id), key=lambda t: (t.txn_date, t.row_index))
    classifications = _current_classification_map(session, txns)

    salary_txns = [t for t in txns if classifications[t.id] and classifications[t.id].category == TransactionCategory.SALARY]
    obligation_txns = [t for t in txns if classifications[t.id] and classifications[t.id].category in (TransactionCategory.LOAN_EMI, TransactionCategory.RENT)]
    balance_txns = [t for t in txns if t.balance is not None]

    if not salary_txns:
        return {
            "name": "salary_to_obligation_cleansing_cycle", "cycles": [],
            "method": "Days from salary credit to recurring-obligation clearance and/or balance falling below threshold.",
            "caveats": ["No SALARY credits found; cycle not computable."], "low_balance_threshold": float(threshold),
        }

    cycles = []
    for i, sal in enumerate(salary_txns):
        next_salary_date = salary_txns[i + 1].txn_date if i + 1 < len(salary_txns) else None
        window_end = next_salary_date if next_salary_date else None

        obligations_in_window = [
            o for o in obligation_txns
            if o.txn_date >= sal.txn_date and (window_end is None or o.txn_date < window_end)
        ]
        last_obligation_date = max((o.txn_date for o in obligations_in_window), default=None)

        low_balance_date = None
        for b in balance_txns:
            if b.txn_date < sal.txn_date:
                continue
            if window_end is not None and b.txn_date >= window_end:
                break
            if b.balance < threshold:
                low_balance_date = b.txn_date
                break

        cycles.append({
            "salary_txn_id": sal.id,
            "salary_date": sal.txn_date.isoformat(),
            "salary_amount": float(sal.credit),
            "obligation_txn_ids": [o.id for o in obligations_in_window],
            "obligations_cleared_by": last_obligation_date.isoformat() if last_obligation_date else None,
            "days_salary_to_obligations_cleared": (last_obligation_date - sal.txn_date).days if last_obligation_date else None,
            "days_salary_to_low_balance": (low_balance_date - sal.txn_date).days if low_balance_date else None,
            "low_balance_date": low_balance_date.isoformat() if low_balance_date else None,
        })

    return {
        "name": "salary_to_obligation_cleansing_cycle",
        "cycles": cycles,
        "method": "For each salary credit: days to clear EMI/RENT obligations in the following pay period, and days until balance first falls below the configured low-balance threshold.",
        "caveats": ["A low balance alone does not by itself indicate financial distress."],
        "low_balance_threshold": float(threshold),
    }


def compute_discretionary_spending_ratio(session: Session, account_id: int) -> dict:
    """
    (Eligible discretionary outflows / Total eligible monthly outflows) * 100.
    Internal transfers excluded; refunds not double-counted (refunds are
    credits, never summed into outflows here). Unknown expenses are kept
    unclassified, not forced into either bucket.
    """
    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, coverage_grid = _coverage_caveats(session, account_id)

    discretionary_total = Decimal(0)
    essential_total = Decimal(0)
    unclassified_total = Decimal(0)
    included, excluded = [], []
    by_month_disc = defaultdict(Decimal)
    by_month_total = defaultdict(Decimal)

    for t in txns:
        if t.debit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        subcat = cls.subcategory if cls else None

        if cat == TransactionCategory.INTERNAL_TRANSFER:
            excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "internal transfer"})
            continue

        disc = is_discretionary(cat, subcat)
        month_key = t.txn_date.strftime("%Y-%m")
        by_month_total[month_key] += t.debit

        if disc is True:
            discretionary_total += t.debit
            by_month_disc[month_key] += t.debit
            included.append({**_txn_ref(t, cat, t.debit), "bucket": "discretionary"})
        elif disc is False:
            essential_total += t.debit
            included.append({**_txn_ref(t, cat, t.debit), "bucket": "essential"})
        else:
            unclassified_total += t.debit
            excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "unclassified expense - not forced into a bucket"})

    total_eligible = discretionary_total + essential_total
    if total_eligible == 0:
        return {
            "name": "discretionary_spending_ratio", "value": None, "period": "all available months",
            "method": "(Discretionary outflows / total eligible outflows) * 100.",
            "included": included, "excluded": excluded,
            "caveats": caveats + ["No classifiable (discretionary/essential) spending found."],
        }

    ratio = (discretionary_total / total_eligible) * 100

    return {
        "name": "discretionary_spending_ratio",
        "value": float(ratio),
        "period": "all available months",
        "method": "(Discretionary outflows [dining/entertainment/shopping/travel/subscriptions] / total eligible outflows [discretionary + essential]) * 100. Internal transfers excluded; unknown expenses kept unclassified.",
        "included": included,
        "excluded": excluded,
        "caveats": caveats + ([f"₹{float(unclassified_total):.2f} in expenses could not be classified as discretionary or essential and is excluded from the ratio."] if unclassified_total else []),
        "discretionary_total": float(discretionary_total),
        "essential_total": float(essential_total),
        "by_month_discretionary": {k: float(v) for k, v in sorted(by_month_disc.items())},
        "by_month_total": {k: float(v) for k, v in sorted(by_month_total.items())},
    }


def get_individual_metrics(session: Session, account_id: int) -> dict:
    return {
        "account_id": account_id,
        "vnmi": compute_vnmi(session, account_id),
        "namb": compute_namb(session, account_id),
        "foir": compute_foir(session, account_id),
        "salary_to_obligation_cleansing_cycle": compute_salary_to_obligation_cleansing_cycle(session, account_id),
        "discretionary_spending_ratio": compute_discretionary_spending_ratio(session, account_id),
    }
