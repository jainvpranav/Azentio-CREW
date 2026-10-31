from datetime import date
from decimal import Decimal as D

from app.pipeline.redflags import compute_nsf_bounce_counter, compute_round_tripping, compute_eod_balance_stress


def test_nsf_bounce_counter_groups_fee_and_return(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 5), "NACH RTN - INSUFFICIENT FUNDS", debit=D("500"))
    make_txn(account, 1, date(2026, 4, 5), "NACH RETURN CHARGES", debit=D("50"))

    result = compute_nsf_bounce_counter(session, account.id)
    assert result["total_count"] == 1  # grouped into a single failure event
    assert len(result["events"][0]["txn_ids"]) == 2


def test_round_tripping_detects_matching_outflow_then_inflow(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 5), "NEFT TO VENDOR X", debit=D("100000"))
    make_txn(account, 1, date(2026, 4, 6), "NEFT FROM VENDOR X", credit=D("99500"))

    result = compute_round_tripping(session, account.id)
    assert result["total_count"] == 1
    assert result["label"] == "POSSIBLE_CIRCULAR_FLOW"


def test_eod_balance_stress_counts_low_days(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 1), "OPEN", credit=D("2000"), balance=D("2000"))
    make_txn(account, 1, date(2026, 4, 2), "SPEND", debit=D("1900"), balance=D("100"))
    make_txn(account, 1, date(2026, 4, 10), "TOPUP", credit=D("5000"), balance=D("5100"))

    result = compute_eod_balance_stress(session, account.id, threshold=D("500"))
    assert result["days_below_threshold"] == 8  # Apr 2-9 inclusive
    assert result["lowest_balance"] == 100.0
