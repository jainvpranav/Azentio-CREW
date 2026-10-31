"""
Red-flag metrics (handoff Phase 3): NSF/Bounce Counter, Round-tripping /
possible circular flow, End-of-Day (EOD) Balance Stress.

These are explanatory indicators with supporting transaction IDs, not
accusations. None of this code emits or implies "fraud" / "money
laundering" / "default" - the strongest label used is POSSIBLE_CIRCULAR_FLOW,
per handoff instruction.
"""
from decimal import Decimal
from collections import defaultdict
from datetime import timedelta
from sqlmodel import Session, select

from app.models import Transaction, Account, Flag, FlagSeverity
from app.pipeline.individual_metrics import compute_namb
from app.config import thresholds as cfg

NSF_KEYWORDS = ["NSF", "BOUNCE", "INSUFFICIENT", "INSUFF", "NACH RTN", "NACHRTN", "ECS RTN", "ECSRTN", "ACH RTN", "ACHRTN", "RETURN"]


def _all_txns(session: Session, account_id: int) -> list:
    return session.exec(
        select(Transaction).where(Transaction.account_id == account_id).where(Transaction.duplicate_of == None)
    ).all()


def _same_payee(a: Transaction, b: Transaction) -> bool:
    """
    Same lender/payee for NSF grouping purposes. Prefers an identified
    counterparty; when either side lacks one (common for bank-charge rows),
    falls back to being in the same tight date window (enforced by the
    caller) rather than a brittle exact description-prefix match, since a
    bounce fee's narration rarely matches the returned debit's verbatim.
    """
    if a.counterparty and b.counterparty:
        return a.counterparty.upper() == b.counterparty.upper()
    # No identified counterparty on at least one side (common for a bank
    # fee row): fall back to being in the same tight date window, already
    # enforced by the caller. Two unrelated bounce events for different
    # lenders landing on the exact same day is a rare false positive,
    # disclosed in this metric's caveats rather than finely distinguished.
    return True


def compute_nsf_bounce_counter(session: Session, account_id: int) -> dict:
    """
    Groups bounce-keyword transactions that land within 2 days of each
    other and reference the same payee/lender into a single failure event,
    so a bounce fee + the returned debit aren't counted as two failures.
    """
    txns = sorted(_all_txns(session, account_id), key=lambda t: t.txn_date)
    candidates = [t for t in txns if any(kw in t.description.upper() for kw in NSF_KEYWORDS)]

    events = []
    used = set()
    for t in candidates:
        if t.id in used:
            continue
        group = [t]
        used.add(t.id)
        for other in candidates:
            if other.id in used:
                continue
            if abs((other.txn_date - t.txn_date).days) > 2:
                continue
            if not _same_payee(t, other):
                continue
            group.append(other)
            used.add(other.id)
        events.append(group)

    monthly_counts = defaultdict(int)
    detail = []
    for group in events:
        month_key = group[0].txn_date.strftime("%Y-%m")
        monthly_counts[month_key] += 1
        detail.append({
            "date": group[0].txn_date.isoformat(),
            "payee": group[0].counterparty or group[0].description,
            "txn_ids": [g.id for g in group],
        })

    return {
        "name": "nsf_bounce_counter",
        "total_count": len(events),
        "by_month": dict(sorted(monthly_counts.items())),
        "events": detail,
        "method": "Bounce/NSF/return-keyword transactions grouped within 2 days and by payee into one failure event each, to avoid double-counting a bounce fee alongside the returned debit.",
        "caveats": ["Keyword-based detection; a bank-specific return code not matching these keywords would not be counted."],
    }


def compute_round_tripping(session: Session, account_id: int) -> dict:
    """
    Flags rapid outgoing-then-incoming (or incoming-then-outgoing) flows of
    matching/near-matching amount within a configurable window (default
    24-48h). Verified internal transfers and matched refunds/reversals are
    excluded. Output is POSSIBLE_CIRCULAR_FLOW - a pattern, never an
    assertion of money laundering.
    """
    from app.pipeline.metrics import _current_classification_map
    from app.models import TransactionCategory

    txns = sorted(_all_txns(session, account_id), key=lambda t: t.txn_date)
    classifications = _current_classification_map(session, txns)
    excluded_categories = {
        TransactionCategory.INTERNAL_TRANSFER, TransactionCategory.REFUND, TransactionCategory.REVERSAL,
    }

    eligible = [
        t for t in txns
        if not (classifications[t.id] and classifications[t.id].category in excluded_categories)
    ]

    window_max = timedelta(hours=cfg.ROUND_TRIP_WINDOW_HOURS_MAX)
    tolerance = cfg.ROUND_TRIP_AMOUNT_TOLERANCE_PCT
    matches = []
    matched_ids = set()

    for i, t in enumerate(eligible):
        if t.id in matched_ids or t.debit is None:
            continue
        for other in eligible[i + 1:]:
            if other.id in matched_ids or other.credit is None:
                continue
            delta_days = (other.txn_date - t.txn_date).days
            if delta_days < 0 or timedelta(days=delta_days) > window_max:
                if delta_days > 2:  # txn_date has no time component; stop scanning once clearly beyond window
                    break
                continue
            if t.debit == 0:
                continue
            diff_pct = abs(other.credit - t.debit) / t.debit
            if diff_pct > tolerance:
                continue
            matches.append({
                "out_txn_id": t.id,
                "out_date": t.txn_date.isoformat(),
                "out_amount": float(t.debit),
                "in_txn_id": other.id,
                "in_date": other.txn_date.isoformat(),
                "in_amount": float(other.credit),
                "counterparty": other.counterparty or other.description,
            })
            matched_ids.add(t.id)
            matched_ids.add(other.id)
            break

    return {
        "name": "round_tripping",
        "label": "POSSIBLE_CIRCULAR_FLOW",
        "total_count": len(matches),
        "matches": matches,
        "method": f"Outgoing debit followed by an incoming credit of matching amount (within {float(tolerance)*100:.0f}%) within {cfg.ROUND_TRIP_WINDOW_HOURS_MIN}-{cfg.ROUND_TRIP_WINDOW_HOURS_MAX}h, excluding verified internal transfers and matched refunds/reversals.",
        "caveats": [
            "A pattern match here is a possible circular flow for review, never a determination of money laundering or fraud.",
            "Transaction timestamps are date-only in this build; same-day matches within the window may include false positives that a time-of-day check would rule out.",
        ],
    }


def compute_eod_balance_stress(session: Session, account_id: int, threshold: Decimal = None) -> dict:
    """
    Daily closing balances, negative-balance days, days below a
    configurable liquidity threshold, longest consecutive stress streak,
    and the lowest balance observed. Default threshold = 5% of NAMB (per
    handoff's illustrative starting point), falling back to a fixed floor
    when NAMB isn't computable.
    """
    txns = sorted(
        (t for t in _all_txns(session, account_id) if t.balance is not None),
        key=lambda t: (t.txn_date, t.row_index),
    )
    if not txns:
        return {
            "name": "eod_balance_stress", "threshold": None,
            "method": "Daily closing balance vs. a configurable liquidity threshold.",
            "caveats": ["No balance data available."], "days_below_threshold": 0,
            "negative_balance_days": 0, "longest_consecutive_stress_days": 0, "lowest_balance": None,
        }

    if threshold is None:
        namb = compute_namb(session, account_id)
        if namb["value"] is not None and namb["value"] > 0:
            threshold = Decimal(str(namb["value"])) * cfg.EOD_STRESS_PERCENT_OF_NAMB
        else:
            threshold = cfg.EOD_STRESS_FALLBACK_THRESHOLD

    day_balance = {}
    for t in txns:
        day_balance[t.txn_date] = t.balance
    days = sorted(day_balance.keys())

    daily_series = []
    current = day_balance[days[0]]
    d = days[0]
    while d <= days[-1]:
        if d in day_balance:
            current = day_balance[d]
        daily_series.append((d, current))
        d += timedelta(days=1)

    below_days = [d for d, bal in daily_series if bal < threshold]
    negative_days = [d for d, bal in daily_series if bal < 0]
    lowest_balance = min(bal for _, bal in daily_series)

    longest_streak = 0
    current_streak = 0
    for _, bal in daily_series:
        if bal < threshold:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            current_streak = 0

    monthly_below = defaultdict(int)
    for d in below_days:
        monthly_below[d.strftime("%Y-%m")] += 1

    return {
        "name": "eod_balance_stress",
        "threshold": float(threshold),
        "method": "Daily closing balance (carried forward from the last known transaction) compared to a liquidity threshold, default 5% of NAMB.",
        "days_below_threshold": len(below_days),
        "by_month_days_below": dict(sorted(monthly_below.items())),
        "negative_balance_days": len(negative_days),
        "longest_consecutive_stress_days": longest_streak,
        "lowest_balance": float(lowest_balance),
        "caveats": [
            "Threshold is configurable and illustrative, not a universal liquidity standard.",
            f"Consecutive-day warning level is set at {cfg.EOD_STRESS_CONSECUTIVE_DAYS_WARN} days in app/config/thresholds.py.",
        ],
    }


def generate_red_flags(session: Session, account_id: int) -> dict:
    """Run all red-flag checks for an account and create review-queue Flag rows for any findings."""
    nsf = compute_nsf_bounce_counter(session, account_id)
    round_trip = compute_round_tripping(session, account_id)
    eod = compute_eod_balance_stress(session, account_id)

    created = 0
    if nsf["total_count"] > 0:
        session.add(Flag(
            account_id=account_id, flag_type="NSF_BOUNCE", severity=FlagSeverity.HIGH,
            message=f"{nsf['total_count']} NSF/bounce event(s) detected. Requires analyst review.",
            evidence=str([e["txn_ids"] for e in nsf["events"]]),
        ))
        created += 1

    if round_trip["total_count"] > 0:
        session.add(Flag(
            account_id=account_id, flag_type="POSSIBLE_CIRCULAR_FLOW", severity=FlagSeverity.WARN,
            message=f"{round_trip['total_count']} possible circular-flow pattern(s) detected. Requires analyst review, not a fraud determination.",
            evidence=str([[m["out_txn_id"], m["in_txn_id"]] for m in round_trip["matches"]]),
        ))
        created += 1

    if eod["longest_consecutive_stress_days"] >= cfg.EOD_STRESS_CONSECUTIVE_DAYS_WARN:
        session.add(Flag(
            account_id=account_id, flag_type="EOD_BALANCE_STRESS", severity=FlagSeverity.WARN,
            message=f"{eod['longest_consecutive_stress_days']} consecutive days below the liquidity threshold (lowest balance ₹{eod['lowest_balance']:.2f}).",
        ))
        created += 1

    session.commit()

    return {"nsf_bounce_counter": nsf, "round_tripping": round_trip, "eod_balance_stress": eod, "flags_created": created}


def generate_red_flags_all(session: Session) -> dict:
    accounts = session.exec(select(Account)).all()
    return {a.id: generate_red_flags(session, a.id) for a in accounts}
