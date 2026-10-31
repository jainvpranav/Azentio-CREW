"""
SME borrower metrics (handoff Phase 2): GBT, DSCR, Customer Concentration,
CC/OD Utilization, Trade Inflow-to-Outflow Ratio. Same MetricResult-style
contract as app/pipeline/metrics.py / individual_metrics.py.
"""
from decimal import Decimal
from collections import defaultdict
from datetime import timedelta
from sqlmodel import Session, select

from app.models import Transaction, TransactionCategory, Facility
from app.pipeline.metrics import _current_classification_map, _txn_ref, _coverage_caveats
from app.config import thresholds as cfg

# Operating outflow categories for DSCR's cash-flow estimate: general
# business running costs, excluding the debt service itself (LOAN_EMI) and
# non-operating movements (internal transfers).
OPERATING_OUTFLOW_CATEGORIES = {
    TransactionCategory.OTHER_EXPENSE, TransactionCategory.RENT, TransactionCategory.UTILITIES,
    TransactionCategory.BANK_CHARGES, TransactionCategory.CASH_WITHDRAWAL,
}
VERIFIED_INFLOW_CATEGORIES = {TransactionCategory.BUSINESS_RECEIPT}


def _all_txns(session: Session, account_id: int) -> list:
    return session.exec(select(Transaction).where(Transaction.account_id == account_id)).all()


def compute_gbt(session: Session, account_id: int) -> dict:
    """
    Gross Banking Turnover: sum of verified BUSINESS_RECEIPT credits over
    the period. POSSIBLE_BUSINESS_RECEIPT / UNVERIFIED_CREDIT are reported
    separately so "verified turnover" is never inflated by unconfirmed
    credits (handoff: "Distinguish verified business turnover from total
    account credits").
    """
    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, coverage_grid = _coverage_caveats(session, account_id)

    included, excluded = [], []
    by_month = defaultdict(Decimal)
    unverified_total = Decimal(0)

    for t in txns:
        if t.credit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        if cat in VERIFIED_INFLOW_CATEGORIES:
            included.append(_txn_ref(t, cat, t.credit))
            by_month[t.txn_date.strftime("%Y-%m")] += t.credit
        elif cat in (TransactionCategory.POSSIBLE_BUSINESS_RECEIPT, TransactionCategory.UNVERIFIED_CREDIT):
            unverified_total += t.credit
            excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": "unverified - not counted in GBT"})
        else:
            excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": f"not business turnover ({cat.value if cat else 'unclassified'})"})

    value = sum(by_month.values()) if by_month else Decimal(0)

    return {
        "name": "gbt",
        "value": float(value),
        "period": "all available months",
        "method": "Sum of verified BUSINESS_RECEIPT credits. Excludes internal transfers, refunds/reversals, loan disbursements and unverified credits.",
        "included": included,
        "excluded": excluded,
        "caveats": caveats + ([f"₹{float(unverified_total):.2f} in additional credits are unverified (new/unconfirmed counterparty) and excluded from GBT."] if unverified_total else []),
        "by_month": {k: float(v) for k, v in sorted(by_month.items())},
        "unverified_credits_total": float(unverified_total),
    }


def compute_dscr(session: Session, account_id: int) -> dict:
    """
    DSCR = Net Operating Cash Flow / Total Debt Service.
    Operating cash flow = verified business inflows - operating outflows.
    Debt service = LOAN_EMI debits (principal+interest combined - cannot be
    separated from a bank statement alone, disclosed as a limitation).
    """
    gbt = compute_gbt(session, account_id)
    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, _ = _coverage_caveats(session, account_id)

    operating_outflow = Decimal(0)
    debt_service = Decimal(0)
    included, excluded = [], []
    months_seen = set()

    for t in txns:
        if t.debit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        months_seen.add(t.txn_date.strftime("%Y-%m"))
        if cat == TransactionCategory.LOAN_EMI:
            debt_service += t.debit
            included.append({**_txn_ref(t, cat, t.debit), "bucket": "debt_service"})
        elif cat in OPERATING_OUTFLOW_CATEGORIES:
            operating_outflow += t.debit
            included.append({**_txn_ref(t, cat, t.debit), "bucket": "operating_outflow"})
        else:
            excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "not an operating outflow or debt-service debit"})

    months = max(len(months_seen), 1)
    monthly_inflow = Decimal(str(gbt["value"])) / months
    monthly_outflow = operating_outflow / months
    monthly_debt_service = debt_service / months
    net_operating_cash_flow = monthly_inflow - monthly_outflow

    extra_caveats = list(caveats) + [
        "Debt service combines principal and interest (cannot be separated from bank-statement data alone)."
    ]

    if monthly_debt_service == 0:
        return {
            "name": "dscr", "value": None, "period": "average per month",
            "method": "Net Operating Cash Flow / Total Debt Service.",
            "included": included, "excluded": excluded,
            "caveats": extra_caveats + ["No identifiable debt-service (LOAN_EMI) debits in period - DSCR not computable."],
            "net_operating_cash_flow": float(net_operating_cash_flow), "band": "NOT_AVAILABLE",
        }

    dscr = net_operating_cash_flow / monthly_debt_service

    if dscr < cfg.DSCR_SHORTFALL_MAX:
        band = "possible_shortfall"
    elif dscr >= cfg.DSCR_STRONG_MIN:
        band = "strong_coverage"
    else:
        band = "adequate_coverage"

    return {
        "name": "dscr",
        "value": float(dscr),
        "period": "average per month",
        "method": "Net Operating Cash Flow (verified business inflow - operating outflow) / Total Debt Service (LOAN_EMI), averaged per month.",
        "included": included,
        "excluded": excluded,
        "caveats": extra_caveats,
        "net_operating_cash_flow": float(net_operating_cash_flow),
        "monthly_debt_service": float(monthly_debt_service),
        "band": band,
        "band_thresholds": {"shortfall_max": float(cfg.DSCR_SHORTFALL_MAX), "strong_min": float(cfg.DSCR_STRONG_MIN)},
    }


def compute_customer_concentration(session: Session, account_id: int) -> dict:
    """
    Top-1 / top-3 customer share of verified business inflows, by
    identifiable counterparty. Own-account transfers and unverified
    credits are excluded. A credit with no identifiable counterparty is
    grouped under "UNKNOWN_COUNTERPARTY" and reported, not silently
    dropped or merged into a real customer's total.
    """
    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, _ = _coverage_caveats(session, account_id)

    by_customer = defaultdict(Decimal)
    included, excluded = [], []

    for t in txns:
        if t.credit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        if cat not in VERIFIED_INFLOW_CATEGORIES:
            excluded.append({**_txn_ref(t, cat, t.credit), "exclusion_reason": "not a verified business receipt"})
            continue
        key = t.counterparty or "UNKNOWN_COUNTERPARTY"
        by_customer[key] += t.credit
        included.append({**_txn_ref(t, cat, t.credit), "counterparty": key})

    total = sum(by_customer.values())
    if total == 0:
        return {
            "name": "customer_concentration", "top1_share": None, "top3_share": None,
            "method": "Top customer inflow / total verified business inflow.",
            "included": included, "excluded": excluded,
            "caveats": caveats + ["No verified business receipts found."],
        }

    ranked = sorted(by_customer.items(), key=lambda kv: kv[1], reverse=True)
    top1_share = float(ranked[0][1] / total * 100)
    top3_total = sum(v for _, v in ranked[:3])
    top3_share = float(top3_total / total * 100)

    unknown_share = float(by_customer.get("UNKNOWN_COUNTERPARTY", Decimal(0)) / total * 100)
    extra_caveats = list(caveats)
    if unknown_share:
        extra_caveats.append(f"{unknown_share:.1f}% of verified inflow has no identifiable counterparty and is grouped as UNKNOWN_COUNTERPARTY.")

    return {
        "name": "customer_concentration",
        "top1_share": top1_share,
        "top1_customer": ranked[0][0],
        "top3_share": top3_share,
        "top3_customers": [c for c, _ in ranked[:3]],
        "ranked_customers": [{"counterparty": c, "amount": float(v), "share_pct": float(v / total * 100)} for c, v in ranked],
        "method": "Top-1 and top-3 customer inflow shares of total verified business receipts, by identifiable counterparty.",
        "included": included,
        "excluded": excluded,
        "caveats": extra_caveats,
        "top1_elevated": top1_share > float(cfg.CONCENTRATION_TOP1_ELEVATED_MIN),
        "top3_elevated": top3_share > float(cfg.CONCENTRATION_TOP3_ELEVATED_MIN),
        "thresholds": {"top1_elevated_min": float(cfg.CONCENTRATION_TOP1_ELEVATED_MIN), "top3_elevated_min": float(cfg.CONCENTRATION_TOP3_ELEVATED_MIN)},
    }


def compute_cc_od_utilization(session: Session, account_id: int) -> dict:
    """
    Average Drawn Balance / Sanctioned Credit Limit * 100.
    Requires a Facility row with a sanctioned_limit for this account
    (never inferred from transaction swings). Missing => NOT_AVAILABLE,
    naming exactly what's needed (handoff instruction).
    """
    facility = session.exec(
        select(Facility).where(Facility.account_id == account_id).where(Facility.facility_type == "OD")
    ).first() or session.exec(
        select(Facility).where(Facility.account_id == account_id).where(Facility.facility_type == "CC")
    ).first()

    if not facility or facility.sanctioned_limit is None:
        return {
            "name": "cc_od_utilization", "value": "NOT_AVAILABLE",
            "method": "Average Drawn Balance / Sanctioned Credit Limit * 100.",
            "included": [], "excluded": [],
            "caveats": [
                "No facility/sanctioned-limit metadata available for this account. "
                "Required: facility type (CC/OD) and sanctioned credit limit, supplied by an analyst "
                "(never inferred from transaction amounts)."
            ],
            "missing_metadata": ["facility_type", "sanctioned_limit"],
        }

    txns = [t for t in _all_txns(session, account_id) if t.balance is not None and t.duplicate_of is None]
    if not txns:
        return {
            "name": "cc_od_utilization", "value": "NOT_AVAILABLE",
            "method": "Average Drawn Balance / Sanctioned Credit Limit * 100.",
            "included": [], "excluded": [],
            "caveats": ["Facility metadata present but no balance history available for this account."],
            "missing_metadata": ["balance_history"],
        }

    # Drawn amount = negative balance magnitude (statement balance convention:
    # negative = overdrawn). See ASSUMPTIONS.md A-010.
    txns_sorted = sorted(txns, key=lambda t: (t.txn_date, t.row_index))
    day_balance = {t.txn_date: t.balance for t in txns_sorted}
    days = sorted(day_balance.keys())
    total_days = (days[-1] - days[0]).days + 1 if len(days) > 1 else 1

    running_sum = Decimal(0)
    current = day_balance[days[0]]
    d = days[0]
    while d <= days[-1]:
        if d in day_balance:
            current = day_balance[d]
        drawn = -current if current < 0 else Decimal(0)
        running_sum += drawn
        d += timedelta(days=1)

    avg_drawn = running_sum / total_days
    utilization = (avg_drawn / facility.sanctioned_limit) * 100

    return {
        "name": "cc_od_utilization",
        "value": float(utilization),
        "average_drawn_balance": float(avg_drawn),
        "sanctioned_limit": float(facility.sanctioned_limit),
        "method": "Average Drawn Balance (mean of daily overdrawn amount) / Sanctioned Credit Limit * 100.",
        "included": [_txn_ref(t, None, t.balance) for t in txns_sorted],
        "excluded": [],
        "caveats": [
            "Drawn balance is read from the account's daily closing balance (negative = overdrawn); "
            "this assumes that statement convention - see ASSUMPTIONS.md A-010."
        ],
        "liquidity_pressure": utilization > float(cfg.CC_OD_UTILIZATION_PRESSURE_MIN),
        "pressure_threshold": float(cfg.CC_OD_UTILIZATION_PRESSURE_MIN),
    }


def compute_trade_inflow_outflow_ratio(session: Session, account_id: int) -> dict:
    """
    Verified Business Receipts / Verified Business Payables * 100.
    Payables = identifiable supplier/operating-expense outflows
    (OTHER_EXPENSE + RENT + UTILITIES), excluding debt service and
    internal transfers. When payables are zero/unavailable, returns
    NOT_AVAILABLE rather than dividing by zero or implying "infinite".
    """
    gbt = compute_gbt(session, account_id)
    txns = _all_txns(session, account_id)
    classifications = _current_classification_map(session, txns)
    caveats, _ = _coverage_caveats(session, account_id)

    payables = Decimal(0)
    included, excluded = [], []
    for t in txns:
        if t.debit is None or t.duplicate_of is not None:
            continue
        cls = classifications[t.id]
        cat = cls.category if cls else None
        if cat in (TransactionCategory.OTHER_EXPENSE, TransactionCategory.RENT, TransactionCategory.UTILITIES):
            payables += t.debit
            included.append({**_txn_ref(t, cat, t.debit), "bucket": "payable"})
        else:
            excluded.append({**_txn_ref(t, cat, t.debit), "exclusion_reason": "not a supplier/operating payable"})

    receipts = Decimal(str(gbt["value"]))

    if payables == 0:
        return {
            "name": "trade_inflow_outflow_ratio", "value": "NOT_AVAILABLE",
            "receipts": float(receipts), "payables": 0.0,
            "method": "Verified Business Receipts / Verified Business Payables * 100.",
            "included": included, "excluded": excluded,
            "caveats": caveats + ["No identifiable payables (supplier/operating outflows) in period; ratio not computable."],
        }

    ratio = (receipts / payables) * 100

    return {
        "name": "trade_inflow_outflow_ratio",
        "value": float(ratio),
        "receipts": float(receipts),
        "payables": float(payables),
        "method": "Verified Business Receipts (GBT) / Verified Business Payables (OTHER_EXPENSE + RENT + UTILITIES debits) * 100.",
        "included": included,
        "excluded": excluded,
        "caveats": caveats,
    }


def get_sme_metrics(session: Session, account_id: int) -> dict:
    return {
        "account_id": account_id,
        "gbt": compute_gbt(session, account_id),
        "dscr": compute_dscr(session, account_id),
        "customer_concentration": compute_customer_concentration(session, account_id),
        "cc_od_utilization": compute_cc_od_utilization(session, account_id),
        "trade_inflow_outflow_ratio": compute_trade_inflow_outflow_ratio(session, account_id),
    }
