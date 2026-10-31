"""
Category-specific anomaly detection (handoff Phase 1's per-category anomaly
lists). Classification (what a transaction IS) and anomaly detection
(whether it's unusual) are kept separate here: this module only reads
existing Classification rows, never changes them. An anomaly flags a
transaction for explanation/review - it is never read as proof of fraud,
default, or any wrongdoing (handoff instruction, applies throughout).

Each public `check_*` function returns {flag_type, count, items, method}
and is also responsible for writing matching Flag rows so the existing
review queue (app/pipeline/flags.py:get_flag_queue) picks them up
alongside the data-quality flags. `run_all` executes every check for one
account; call from the same place process-all/generate_all_flags already
runs from (app/api/statements.py:process_all_documents).
"""
import json
from decimal import Decimal
from collections import defaultdict
from sqlmodel import Session, select

from app.models import Transaction, Account, Flag, FlagSeverity, TransactionCategory
from app.pipeline.metrics import _current_classification_map
from app.pipeline.behavioral import median_deviation
from app.config import thresholds as cfg

SUBSCRIPTION_KEYWORDS = ["SUBSCRIPTION", "NETFLIX", "PRIME", "HOTSTAR", "SPOTIFY", "MEMBERSHIP", "ICLOUD", "GOOGLEONE"]


def _txns(session: Session, account_id: int) -> list:
    return session.exec(
        select(Transaction).where(Transaction.account_id == account_id).where(Transaction.duplicate_of == None)
    ).all()


def _classified(session: Session, txns: list) -> dict:
    return _current_classification_map(session, txns)


def _by_category(classifications: dict, txns: list, category: TransactionCategory) -> list:
    return [t for t in txns if classifications.get(t.id) and classifications[t.id].category == category]


def _monthly_sum(txns: list, field: str) -> dict:
    out = defaultdict(Decimal)
    for t in txns:
        amt = getattr(t, field)
        if amt is not None:
            out[t.txn_date.strftime("%Y-%m")] += amt
    return dict(out)


def _flag(session: Session, account_id: int, flag_type: str, severity: FlagSeverity, message: str, txn_ids: list) -> Flag:
    f = Flag(account_id=account_id, flag_type=flag_type, severity=severity, message=message,
              evidence=json.dumps(txn_ids) if txn_ids else None)
    session.add(f)
    return f


def _near_duplicates(txns: list, amount_field: str, window_days: int, group_key_fn) -> list:
    """Generic same-amount-within-window near-duplicate finder."""
    sorted_txns = sorted(txns, key=lambda t: t.txn_date)
    pairs = []
    used = set()
    for i, t in enumerate(sorted_txns):
        if t.id in used or getattr(t, amount_field) is None:
            continue
        for other in sorted_txns[i + 1:]:
            if other.id in used or getattr(other, amount_field) is None:
                continue
            if (other.txn_date - t.txn_date).days > window_days:
                break
            if getattr(other, amount_field) != getattr(t, amount_field):
                continue
            if group_key_fn(t) != group_key_fn(other):
                continue
            pairs.append((t, other))
            used.add(t.id)
            used.add(other.id)
            break
    return pairs


def _deviation_flags(session, account_id, txns, field, flag_type, severity, label):
    """Shared 'sudden increase/decrease vs own history' check over a monthly series."""
    by_month = _monthly_sum(txns, field)
    months = sorted(by_month.keys())
    if len(months) < cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION + 1:
        return {"flag_type": flag_type, "count": 0, "items": [], "method": f"Deviation of latest month's {label} vs historical median.", "caveats": ["Insufficient history."]}

    latest = months[-1]
    history = [by_month[m] for m in months[:-1]]
    dev = median_deviation(by_month[latest], history)
    items = []
    if dev.get("severity") in ("warn", "high"):
        _flag(session, account_id, flag_type, FlagSeverity.WARN if dev["severity"] == "warn" else FlagSeverity.HIGH,
              f"{label} in {latest} deviates {dev['deviation_pct']:.0f}% from historical median (₹{dev['baseline_median']:.0f}).",
              [t.id for t in txns if t.txn_date.strftime("%Y-%m") == latest])
        items.append({"month": latest, **dev})
    return {"flag_type": flag_type, "count": len(items), "items": items, "method": f"Deviation of latest month's {label} vs historical median.", "by_month": {k: float(v) for k, v in by_month.items()}}


# ===================== 1. Internal transfers =====================

def check_internal_transfer_anomalies(session: Session, account_id: int) -> dict:
    txns = _txns(session, account_id)
    classifications = _classified(session, txns)
    transfers = _by_category(classifications, txns, TransactionCategory.INTERNAL_TRANSFER)
    results = {}

    # Unmatched transfer: classified via name-heuristic (XFER_SELF) rather
    # than a confirmed cross-account pair (XFER_PAIR) - the counterpart leg
    # wasn't found among uploaded accounts.
    unmatched = [t for t in transfers if classifications[t.id].rule_id == "XFER_SELF"]
    if unmatched:
        _flag(session, account_id, "UNMATCHED_TRANSFER", FlagSeverity.INFO,
              f"{len(unmatched)} internal transfer(s) classified by holder-name match only; no corresponding leg found among uploaded accounts.",
              [t.id for t in unmatched])
    results["unmatched_transfer"] = {"count": len(unmatched), "txn_ids": [t.id for t in unmatched]}

    # Possible duplicate transfer: two transfer debits, same amount, same
    # direction, within 2 days.
    debit_transfers = [t for t in transfers if t.debit is not None]
    dup_pairs = _near_duplicates(debit_transfers, "debit", 2, lambda t: t.counterparty or t.description[:20])
    for a, b in dup_pairs:
        _flag(session, account_id, "POSSIBLE_DUPLICATE_TRANSFER", FlagSeverity.WARN,
              f"Two internal transfers of ₹{a.debit} within 2 days to the same counterparty.", [a.id, b.id])
    results["possible_duplicate_transfer"] = {"count": len(dup_pairs), "pairs": [[a.id, b.id] for a, b in dup_pairs]}

    # Unusually large transfer: amount deviation vs own history.
    results["unusually_large_transfer"] = _deviation_flags(
        session, account_id, debit_transfers, "debit", "UNUSUALLY_LARGE_TRANSFER", FlagSeverity.WARN, "monthly transfer total"
    )

    # Unusual transfer frequency: count/month deviation.
    monthly_counts = defaultdict(int)
    for t in transfers:
        monthly_counts[t.txn_date.strftime("%Y-%m")] += 1
    months = sorted(monthly_counts.keys())
    if len(months) >= cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION + 1:
        dev = median_deviation(Decimal(monthly_counts[months[-1]]), [Decimal(monthly_counts[m]) for m in months[:-1]])
        if dev.get("severity") in ("warn", "high"):
            _flag(session, account_id, "UNUSUAL_TRANSFER_FREQUENCY", FlagSeverity.WARN,
                  f"{monthly_counts[months[-1]]} internal transfers in {months[-1]}, a {dev['deviation_pct']:.0f}% deviation from the historical monthly median.", [])
        results["unusual_transfer_frequency"] = dev
    else:
        results["unusual_transfer_frequency"] = {"provisional": True}

    session.commit()
    return results


# ===================== 2. Salary =====================

def check_salary_anomalies(session: Session, account_id: int) -> dict:
    txns = _txns(session, account_id)
    classifications = _classified(session, txns)
    salary_txns = sorted(_by_category(classifications, txns, TransactionCategory.SALARY), key=lambda t: t.txn_date)
    results = {}

    results["sudden_change"] = _deviation_flags(
        session, account_id, salary_txns, "credit", "SALARY_SUDDEN_CHANGE", FlagSeverity.WARN, "monthly salary total"
    )

    # Missing or delayed expected salary: based on the typical gap between
    # consecutive salary credits; if more than 1.5x the typical gap has
    # elapsed since the last one (and we're within available data), flag.
    if len(salary_txns) >= 2:
        gaps = [(salary_txns[i + 1].txn_date - salary_txns[i].txn_date).days for i in range(len(salary_txns) - 1)]
        typical_gap = sorted(gaps)[len(gaps) // 2]
        last = salary_txns[-1]
        all_txn_dates = [t.txn_date for t in txns]
        data_end = max(all_txn_dates) if all_txn_dates else last.txn_date
        days_since_last = (data_end - last.txn_date).days
        if days_since_last > typical_gap * 1.5:
            _flag(session, account_id, "MISSING_OR_DELAYED_SALARY", FlagSeverity.WARN,
                  f"No salary credit for {days_since_last} days since {last.txn_date} (typical gap: {typical_gap} days).", [last.id])
            results["missing_or_delayed"] = {"flagged": True, "days_since_last": days_since_last, "typical_gap": typical_gap}
        else:
            results["missing_or_delayed"] = {"flagged": False, "days_since_last": days_since_last, "typical_gap": typical_gap}

        # Unusual payment frequency: a gap well outside the recurring window.
        unusual_gaps = [g for g in gaps if g < 20 or g > 40]
        if unusual_gaps:
            _flag(session, account_id, "UNUSUAL_SALARY_FREQUENCY", FlagSeverity.INFO,
                  f"{len(unusual_gaps)} salary gap(s) outside the typical 20-40 day window: {unusual_gaps}.", [t.id for t in salary_txns])
        results["unusual_frequency"] = {"gaps": gaps, "unusual_gaps": unusual_gaps}
    else:
        results["missing_or_delayed"] = {"provisional": True}
        results["unusual_frequency"] = {"provisional": True}

    # Change in salary source: a new salary txn whose description shares no
    # token with any prior salary txn's description AND no SAL/SALARY/PAYROLL
    # keyword (the amount+timing cluster already tolerates employer renames
    # with a shared keyword; a change with neither is worth a human look).
    if len(salary_txns) >= 2:
        from app.pipeline.pairing import _desc_tokens, SALARY_KEYWORDS
        prior_tokens = set()
        for t in salary_txns[:-1]:
            prior_tokens |= _desc_tokens(t.description)
        latest = salary_txns[-1]
        latest_tokens = _desc_tokens(latest.description)
        has_keyword = any(kw in latest.description.upper() for kw in SALARY_KEYWORDS)
        if not (latest_tokens & prior_tokens) and not has_keyword:
            _flag(session, account_id, "CHANGE_IN_SALARY_SOURCE", FlagSeverity.WARN,
                  f"Latest salary credit's description shares no wording with prior salary credits: '{latest.description}'.", [latest.id])
            results["change_in_source"] = {"flagged": True, "txn_id": latest.id}
        else:
            results["change_in_source"] = {"flagged": False}

    session.commit()
    return results


# ===================== 3. Business receipts =====================

def check_business_receipt_anomalies(session: Session, account_id: int) -> dict:
    txns = _txns(session, account_id)
    classifications = _classified(session, txns)
    receipts = _by_category(classifications, txns, TransactionCategory.BUSINESS_RECEIPT)
    unverified = (_by_category(classifications, txns, TransactionCategory.POSSIBLE_BUSINESS_RECEIPT)
                  + _by_category(classifications, txns, TransactionCategory.UNVERIFIED_CREDIT))
    results = {}

    results["sudden_increase"] = _deviation_flags(
        session, account_id, receipts, "credit", "BUSINESS_RECEIPT_SUDDEN_INCREASE", FlagSeverity.WARN, "monthly business receipt total"
    )

    # Unusually large single credit: vs the median individual receipt (not monthly total).
    amounts = sorted(t.credit for t in receipts)
    if len(amounts) >= cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION + 1:
        med = amounts[len(amounts) // 2]
        large = [t for t in receipts if med > 0 and t.credit >= med * (1 + cfg.DEVIATION_HIGH_PCT / 100)]
        for t in large:
            _flag(session, account_id, "UNUSUALLY_LARGE_BUSINESS_RECEIPT", FlagSeverity.WARN,
                  f"Single business receipt of ₹{t.credit} is well above the typical ₹{med}.", [t.id])
        results["unusually_large_single_credit"] = {"count": len(large), "txn_ids": [t.id for t in large], "median": float(med)}
    else:
        results["unusually_large_single_credit"] = {"provisional": True}

    dup_pairs = _near_duplicates(receipts, "credit", 3, lambda t: t.counterparty or t.description[:20])
    for a, b in dup_pairs:
        _flag(session, account_id, "POSSIBLE_DUPLICATE_BUSINESS_PAYMENT", FlagSeverity.WARN,
              f"Two business receipts of ₹{a.credit} from the same counterparty within 3 days.", [a.id, b.id])
    results["possible_duplicate_payment"] = {"count": len(dup_pairs), "pairs": [[a.id, b.id] for a, b in dup_pairs]}

    if unverified:
        _flag(session, account_id, "UNVERIFIED_CREDIT", FlagSeverity.INFO,
              f"{len(unverified)} credit(s) from a new/unverified counterparty - not automatically suspicious, but purpose is unclear.",
              [t.id for t in unverified])
    results["new_or_unverified_counterparty"] = {"count": len(unverified), "txn_ids": [t.id for t in unverified]}

    # Multiple payments from one sender in a short period.
    by_counterparty = defaultdict(list)
    for t in receipts:
        by_counterparty[t.counterparty or t.description[:20]].append(t)
    burst_flags = []
    for cp, group in by_counterparty.items():
        group = sorted(group, key=lambda t: t.txn_date)
        for i in range(len(group)):
            window = [g for g in group if 0 <= (g.txn_date - group[i].txn_date).days <= 7]
            if len(window) >= 3 and group[i].id not in burst_flags:
                _flag(session, account_id, "MULTIPLE_PAYMENTS_SHORT_PERIOD", FlagSeverity.INFO,
                      f"{len(window)} payments from {cp} within a 7-day window.", [w.id for w in window])
                burst_flags.extend(w.id for w in window)
                break
    results["multiple_payments_short_period"] = {"txn_ids": burst_flags}

    # Credit followed by rapid withdrawal (>=70% of credit amount within 2 days).
    all_debits = sorted([t for t in txns if t.debit is not None], key=lambda t: t.txn_date)
    rapid = []
    for r in receipts:
        for d in all_debits:
            gap = (d.txn_date - r.txn_date).days
            if 0 <= gap <= 2 and d.debit >= r.credit * Decimal("0.7"):
                rapid.append((r, d))
                break
    for r, d in rapid:
        _flag(session, account_id, "CREDIT_FOLLOWED_BY_RAPID_WITHDRAWAL", FlagSeverity.WARN,
              f"₹{r.credit} business receipt on {r.txn_date} followed by a ₹{d.debit} debit within 2 days.", [r.id, d.id])
    results["credit_followed_by_rapid_withdrawal"] = {"count": len(rapid), "pairs": [[r.id, d.id] for r, d in rapid]}

    session.commit()
    return results


# ===================== 4. Refunds and reversals =====================

def check_refund_reversal_anomalies(session: Session, account_id: int) -> dict:
    from app.pipeline.pairing import find_refund_pairs, _desc_tokens, _token_overlap

    txns = _txns(session, account_id)
    classifications = _classified(session, txns)
    refunds = _by_category(classifications, txns, TransactionCategory.REFUND)
    debits_by_id = {t.id: t for t in txns if t.debit is not None}
    refund_pairs = find_refund_pairs(txns)
    results = {}

    no_original = [t for t in refunds if not refund_pairs.get(t.id, {}).get("original_id")]
    for t in no_original:
        _flag(session, account_id, "REFUND_WITHOUT_ORIGINAL", FlagSeverity.WARN,
              f"Refund of ₹{t.credit} with no identifiable original payment.", [t.id])
    results["refund_without_original"] = {"count": len(no_original), "txn_ids": [t.id for t in no_original]}

    by_original = defaultdict(list)
    for t in refunds:
        orig = refund_pairs.get(t.id, {}).get("original_id")
        if orig:
            by_original[orig].append(t)

    multi_refund_ids, exceeding_ids, duplicate_pairs = [], [], []
    for orig_id, group in by_original.items():
        if len(group) >= 2:
            multi_refund_ids.extend(t.id for t in group)
            _flag(session, account_id, "MULTIPLE_REFUNDS_ONE_ORIGINAL", FlagSeverity.WARN,
                  f"{len(group)} refunds reference the same original payment #{orig_id}.", [t.id for t in group])
            close_pairs = _near_duplicates(group, "credit", 3, lambda t: orig_id)
            duplicate_pairs.extend(close_pairs)
            for a, b in close_pairs:
                _flag(session, account_id, "POSSIBLE_DUPLICATE_REFUND", FlagSeverity.WARN,
                      f"Two refunds of ₹{a.credit} against the same original payment within 3 days.", [a.id, b.id])

        original = debits_by_id.get(orig_id)
        if original:
            total_refunded = sum(t.credit for t in group)
            if total_refunded > original.debit:
                exceeding_ids.extend(t.id for t in group)
                _flag(session, account_id, "REFUND_EXCEEDS_ORIGINAL", FlagSeverity.HIGH,
                      f"Refunds totalling ₹{total_refunded} exceed the original payment of ₹{original.debit} (#{orig_id}).", [t.id for t in group] + [orig_id])
            delay_days = (group[0].txn_date - original.txn_date).days
            if delay_days > 30:
                _flag(session, account_id, "DELAYED_REFUND", FlagSeverity.INFO,
                      f"Refund arrived {delay_days} days after the original payment.", [group[0].id, orig_id])

    results["multiple_refunds_one_original"] = {"txn_ids": multi_refund_ids}
    results["possible_duplicate_refund"] = {"count": len(duplicate_pairs), "pairs": [[a.id, b.id] for a, b in duplicate_pairs]}
    results["refund_exceeds_original"] = {"txn_ids": exceeding_ids}

    # Partial refund tracking (informational, not anomalous by itself).
    partial = []
    for orig_id, group in by_original.items():
        original = debits_by_id.get(orig_id)
        if original and sum(t.credit for t in group) < original.debit:
            partial.append({"original_id": orig_id, "refunded": float(sum(t.credit for t in group)), "original_amount": float(original.debit)})
    results["partial_refunds_tracked"] = partial

    # Counterparty mismatch: weak (but accepted, 0.3-0.5) token overlap between refund and its matched original.
    weak_matches = []
    for t in refunds:
        orig_id = refund_pairs.get(t.id, {}).get("original_id")
        original = debits_by_id.get(orig_id) if orig_id else None
        if original:
            overlap = _token_overlap(_desc_tokens(t.description), _desc_tokens(original.description))
            if overlap < 0.5:
                weak_matches.append(t.id)
                _flag(session, account_id, "REFUND_COUNTERPARTY_MISMATCH", FlagSeverity.INFO,
                      f"Refund #{t.id} matched to original #{orig_id} with weak description overlap ({overlap:.0%}); verify counterparty.", [t.id, orig_id])
    results["counterparty_mismatch"] = {"txn_ids": weak_matches}

    # Repeated failed transactions/reversals (not NSF-specific): >=2 REVERSAL
    # txns to/from the same counterparty.
    reversals = _by_category(classifications, txns, TransactionCategory.REVERSAL)
    by_cp = defaultdict(list)
    for t in reversals:
        by_cp[t.counterparty or t.description[:20]].append(t)
    repeated = [g for g in by_cp.values() if len(g) >= 2]
    for g in repeated:
        _flag(session, account_id, "REPEATED_REVERSALS", FlagSeverity.WARN,
              f"{len(g)} reversed transactions with the same counterparty.", [t.id for t in g])
    results["repeated_failed_transactions"] = {"groups": [[t.id for t in g] for g in repeated]}

    session.commit()
    return results


# ===================== 5. Loan EMI =====================

def check_loan_emi_anomalies(session: Session, account_id: int) -> dict:
    txns = _txns(session, account_id)
    classifications = _classified(session, txns)
    emi_txns = sorted(_by_category(classifications, txns, TransactionCategory.LOAN_EMI), key=lambda t: t.txn_date)
    results = {}

    by_lender = defaultdict(list)
    for t in emi_txns:
        by_lender[t.counterparty or t.description[:25]].append(t)

    missing, duplicates, increases, new_recurring = [], [], [], []
    all_dates = [t.txn_date for t in txns]
    data_end = max(all_dates) if all_dates else None

    for lender, group in by_lender.items():
        group = sorted(group, key=lambda t: t.txn_date)
        if len(group) < 2:
            continue

        gaps = [(group[i + 1].txn_date - group[i].txn_date).days for i in range(len(group) - 1)]
        typical_gap = sorted(gaps)[len(gaps) // 2]

        # Expected EMI missing.
        if data_end:
            since_last = (data_end - group[-1].txn_date).days
            if since_last > typical_gap * 1.5:
                missing.append({"lender": lender, "last_date": group[-1].txn_date.isoformat(), "days_since": since_last})
                _flag(session, account_id, "EXPECTED_EMI_MISSING", FlagSeverity.WARN,
                      f"No EMI to {lender} for {since_last} days (typical gap {typical_gap} days). Missing deductions do not by themselves indicate default.", [group[-1].id])

        # Possible duplicate EMI: two same-amount debits <10 days apart.
        dup_pairs = _near_duplicates(group, "debit", 10, lambda t: lender)
        for a, b in dup_pairs:
            duplicates.append([a.id, b.id])
            _flag(session, account_id, "POSSIBLE_DUPLICATE_EMI", FlagSeverity.WARN,
                  f"Two EMI debits of ₹{a.debit} to {lender} within 10 days.", [a.id, b.id])

        # Unexpected EMI increase/decrease vs this lender's own history.
        amounts = [t.debit for t in group]
        dev = median_deviation(amounts[-1], amounts[:-1])
        if dev.get("severity") in ("warn", "high"):
            increases.append({"lender": lender, **dev})
            _flag(session, account_id, "UNEXPECTED_EMI_CHANGE", FlagSeverity.INFO,
                  f"EMI to {lender} changed {dev['deviation_pct']:.0f}% vs its own history (may be a rate change or restructuring).", [group[-1].id])

        # New recurring loan repayment: cluster's first occurrence is recent.
        if data_end and (data_end - group[0].txn_date).days <= 60 and len(group) <= 3:
            new_recurring.append({"lender": lender, "first_seen": group[0].txn_date.isoformat()})

    results["expected_emi_missing"] = missing
    results["possible_duplicate_emi"] = duplicates
    results["unexpected_emi_change"] = increases
    results["new_recurring_loan_repayment"] = new_recurring

    # Debit followed by reversal.
    from app.pipeline.pairing import find_reversal_pairs
    reversal_pairs = find_reversal_pairs(txns)
    reversed_emis = [t.id for t in emi_txns if any(v.get("original_id") == t.id for v in reversal_pairs.values())]
    if reversed_emis:
        _flag(session, account_id, "EMI_DEBIT_FOLLOWED_BY_REVERSAL", FlagSeverity.WARN,
              f"{len(reversed_emis)} EMI debit(s) were reversed.", reversed_emis)
    results["debit_followed_by_reversal"] = reversed_emis

    session.commit()
    return results


# ===================== 6. Common expenses =====================

def check_expense_anomalies(session: Session, account_id: int) -> dict:
    txns = _txns(session, account_id)
    classifications = _classified(session, txns)
    expense_categories = {
        TransactionCategory.OTHER_EXPENSE, TransactionCategory.RENT, TransactionCategory.UTILITIES,
        TransactionCategory.CARD_PAYMENT, TransactionCategory.CASH_WITHDRAWAL,
    }
    expenses = [t for t in txns if classifications.get(t.id) and classifications[t.id].category in expense_categories]
    results = {}

    results["sudden_increase_total_spending"] = _deviation_flags(
        session, account_id, expenses, "debit", "SUDDEN_SPENDING_INCREASE", FlagSeverity.WARN, "monthly total spending"
    )

    # Unusually large purchase, per subcategory.
    by_subcat = defaultdict(list)
    for t in expenses:
        cls = classifications[t.id]
        by_subcat[cls.subcategory or cls.category.value].append(t)
    large_purchases = []
    for subcat, group in by_subcat.items():
        amounts = sorted(t.debit for t in group)
        if len(amounts) < cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION + 1:
            continue
        med = amounts[len(amounts) // 2]
        for t in group:
            if med > 0 and t.debit >= med * (1 + cfg.DEVIATION_HIGH_PCT / 100):
                large_purchases.append(t.id)
        if large_purchases:
            _flag(session, account_id, "UNUSUALLY_LARGE_PURCHASE", FlagSeverity.INFO,
                  f"{len([t for t in group if t.id in large_purchases])} unusually large '{subcat}' purchase(s) vs typical ₹{med}.",
                  [t.id for t in group if t.id in large_purchases])
    results["unusually_large_purchase"] = {"txn_ids": large_purchases}

    # Possible duplicate debit.
    dup_pairs = _near_duplicates(expenses, "debit", 1, lambda t: t.description[:25])
    for a, b in dup_pairs:
        _flag(session, account_id, "POSSIBLE_DUPLICATE_DEBIT", FlagSeverity.WARN,
              f"Two debits of ₹{a.debit} with matching description within 1 day.", [a.id, b.id])
    results["possible_duplicate_debit"] = {"count": len(dup_pairs), "pairs": [[a.id, b.id] for a, b in dup_pairs]}

    # Unusual spending frequency (count/month).
    monthly_counts = defaultdict(int)
    for t in expenses:
        monthly_counts[t.txn_date.strftime("%Y-%m")] += 1
    months = sorted(monthly_counts.keys())
    if len(months) >= cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION + 1:
        dev = median_deviation(Decimal(monthly_counts[months[-1]]), [Decimal(monthly_counts[m]) for m in months[:-1]])
        if dev.get("severity") in ("warn", "high"):
            _flag(session, account_id, "UNUSUAL_SPENDING_FREQUENCY", FlagSeverity.INFO,
                  f"{monthly_counts[months[-1]]} expense transactions in {months[-1]}, a {dev['deviation_pct']:.0f}% deviation from the historical median.", [])
        results["unusual_spending_frequency"] = dev
    else:
        results["unusual_spending_frequency"] = {"provisional": True}

    # New recurring subscription: confirmed recurrence (>=2 occurrences,
    # ~monthly gap, same amount +-5%) with a subscription-like description,
    # whose first occurrence is recent.
    candidates = [t for t in expenses if any(kw in t.description.upper().replace(" ", "") for kw in SUBSCRIPTION_KEYWORDS)]
    by_desc = defaultdict(list)
    for t in candidates:
        by_desc[t.description[:20]].append(t)
    new_subs = []
    data_end = max((t.txn_date for t in txns), default=None)
    for desc, group in by_desc.items():
        group = sorted(group, key=lambda t: t.txn_date)
        if len(group) < 2:
            continue
        gaps_ok = all(20 <= (group[i + 1].txn_date - group[i].txn_date).days <= 40 for i in range(len(group) - 1))
        amounts_ok = all(abs(group[i + 1].debit - group[i].debit) / group[i].debit <= Decimal("0.05") for i in range(len(group) - 1) if group[i].debit)
        if gaps_ok and amounts_ok and data_end and (data_end - group[0].txn_date).days <= 90:
            new_subs.append({"description": desc, "amount": float(group[-1].debit), "first_seen": group[0].txn_date.isoformat()})
            _flag(session, account_id, "NEW_RECURRING_SUBSCRIPTION", FlagSeverity.INFO,
                  f"New recurring subscription confirmed: '{desc}' (~₹{group[-1].debit}/month since {group[0].txn_date}).", [t.id for t in group])
    results["new_recurring_subscription"] = new_subs

    # Unusual cash withdrawals.
    cash = [t for t in expenses if classifications[t.id].category == TransactionCategory.CASH_WITHDRAWAL]
    results["unusual_cash_withdrawals"] = _deviation_flags(
        session, account_id, cash, "debit", "UNUSUAL_CASH_WITHDRAWALS", FlagSeverity.WARN, "monthly cash withdrawal total"
    )

    # Category-level spending spike (per subcategory).
    spikes = []
    for subcat, group in by_subcat.items():
        by_month = _monthly_sum(group, "debit")
        months2 = sorted(by_month.keys())
        if len(months2) < cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION + 1:
            continue
        dev = median_deviation(by_month[months2[-1]], [by_month[m] for m in months2[:-1]])
        if dev.get("severity") in ("warn", "high"):
            spikes.append({"subcategory": subcat, "month": months2[-1], **dev})
            _flag(session, account_id, "CATEGORY_SPENDING_SPIKE", FlagSeverity.INFO,
                  f"'{subcat}' spending in {months2[-1]} deviates {dev['deviation_pct']:.0f}% from its historical median.", [])
    results["category_level_spending_spike"] = spikes

    session.commit()
    return results


def run_all(session: Session, account_id: int) -> dict:
    return {
        "internal_transfer": check_internal_transfer_anomalies(session, account_id),
        "salary": check_salary_anomalies(session, account_id),
        "business_receipt": check_business_receipt_anomalies(session, account_id),
        "refund_reversal": check_refund_reversal_anomalies(session, account_id),
        "loan_emi": check_loan_emi_anomalies(session, account_id),
        "expense": check_expense_anomalies(session, account_id),
    }


def run_all_accounts(session: Session) -> dict:
    accounts = session.exec(select(Account)).all()
    return {a.id: run_all(session, a.id) for a in accounts}
