from datetime import date
from decimal import Decimal as D

from app.pipeline.pairing import (
    find_reversal_pairs,
    find_refund_pairs,
    find_cross_account_transfer_pairs,
    find_salary_clusters,
    find_emi_clusters,
)


def test_reversal_pairs_match_opposite_sides_within_7_days(session, make_account, make_txn):
    account = make_account()
    debit = make_txn(account, 1, date(2026, 4, 1), "CARD PAYMENT XYZ", debit=D("500"))
    reversal = make_txn(account, 1, date(2026, 4, 5), "REVERSAL OF CARD PAYMENT", credit=D("500"))

    pairs = find_reversal_pairs([debit, reversal])
    assert reversal.id in pairs
    assert pairs[reversal.id]["original_id"] == debit.id
    assert debit.id not in pairs  # only the keyword side is marked


def test_reversal_pairs_respect_7_day_window(session, make_account, make_txn):
    account = make_account()
    debit = make_txn(account, 1, date(2026, 4, 1), "CARD PAYMENT", debit=D("500"))
    reversal = make_txn(account, 1, date(2026, 4, 20), "REVERSAL OF CARD PAYMENT", credit=D("500"))

    assert find_reversal_pairs([debit, reversal]) == {}


def test_refund_pairs_match_by_description_overlap(session, make_account, make_txn):
    account = make_account()
    original = make_txn(account, 1, date(2026, 4, 5), "AMAZON.IN ORDER 4521", debit=D("2500"))
    refund = make_txn(account, 1, date(2026, 4, 10), "AMAZON REFUND ORDER 4521", credit=D("2500"))

    pairs = find_refund_pairs([original, refund])
    assert pairs[refund.id]["original_id"] == original.id


def test_refund_pairs_without_a_match_say_so(session, make_account, make_txn):
    account = make_account()
    refund = make_txn(account, 1, date(2026, 4, 10), "CASHBACK REWARD", credit=D("50"))

    pairs = find_refund_pairs([refund])
    assert pairs[refund.id]["original_id"] is None


def test_cross_account_transfer_pairs_both_legs(session, make_account, make_txn):
    acc_a = make_account(account_number="AAAA1111")
    acc_b = make_account(account_number="BBBB2222")
    debit = make_txn(acc_a, 1, date(2026, 4, 3), "NEFT TO OWN A/C", debit=D("50000"))
    credit = make_txn(acc_b, 2, date(2026, 4, 3), "NEFT CR FROM SELF", credit=D("50000"))

    pairs = find_cross_account_transfer_pairs(session)
    assert pairs[debit.id]["pair_id"] == credit.id
    assert pairs[credit.id]["pair_id"] == debit.id
    assert "2222" in pairs[debit.id]["reason"]


def test_salary_cluster_survives_payroll_provider_rename(session, make_account, make_txn):
    account = make_account()
    t1 = make_txn(account, 1, date(2026, 4, 2), "ACME TECH PVT LTD SAL APR", credit=D("45000"))
    t2 = make_txn(account, 1, date(2026, 5, 2), "ACME TECH PVT LTD SAL MAY", credit=D("45000"))
    t3 = make_txn(account, 1, date(2026, 6, 2), "RAZORPAYX PAYROLL ACME", credit=D("45000"))

    clusters = find_salary_clusters([t1, t2, t3])
    assert set(clusters.keys()) == {t1.id, t2.id, t3.id}
    assert clusters[t3.id]["n"] == 3


def test_salary_cluster_requires_at_least_two_occurrences(session, make_account, make_txn):
    account = make_account()
    t1 = make_txn(account, 1, date(2026, 4, 2), "ONE OFF CREDIT", credit=D("45000"))
    assert find_salary_clusters([t1]) == {}


def test_emi_cluster_matches_recurring_same_amount_debit(session, make_account, make_txn):
    account = make_account()
    t1 = make_txn(account, 1, date(2026, 4, 22), "EMI PAYMENT LOAN8842", debit=D("18450"))
    t2 = make_txn(account, 1, date(2026, 5, 22), "EMI PAYMENT LOAN8842", debit=D("18450"))

    clusters = find_emi_clusters([t1, t2])
    assert clusters[t1.id]["n"] == 2
    assert clusters[t2.id]["n"] == 2


def test_emi_cluster_excludes_recurring_utility_bills(session, make_account, make_txn):
    # Regression: a recurring same-amount monthly utility bill looks
    # statistically identical to an EMI and must NOT be swept in.
    account = make_account()
    t1 = make_txn(account, 1, date(2026, 4, 20), "BESCOM ELECTRICITY BILL", debit=D("1450"))
    t2 = make_txn(account, 1, date(2026, 5, 18), "BESCOM ELECTRICITY BILL", debit=D("1450"))

    assert find_emi_clusters([t1, t2]) == {}
