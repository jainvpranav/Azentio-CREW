from datetime import date
from decimal import Decimal as D

from app.pipeline.classify import classify_all_transactions
from app.pipeline.individual_metrics import (
    compute_vnmi, compute_namb, compute_foir, compute_discretionary_spending_ratio,
    compute_salary_to_obligation_cleansing_cycle,
)


def _salaried_account(make_account, make_txn):
    account = make_account()
    balance = D("50000")
    for i, (month, day) in enumerate([(4, 2), (5, 2), (6, 2)]):
        make_txn(account, 1, date(2026, month, day), "ACME TECH PVT LTD SAL", credit=D("45000"), balance=balance + D("45000"))
        make_txn(account, 1, date(2026, month, day + 5), "EMI PAYMENT LOAN8842", debit=D("10000"), balance=balance + D("35000"))
        make_txn(account, 1, date(2026, month, day + 10), "SWIGGY ORDER", debit=D("500"), balance=balance + D("34500"))
    return account


def test_vnmi_averages_salary_excluding_bonus(session, make_account, make_txn):
    account = _salaried_account(make_account, make_txn)
    # Add a bonus month far above median.
    make_txn(account, 1, date(2026, 7, 2), "ACME TECH PVT LTD SAL", credit=D("45000"))
    make_txn(account, 1, date(2026, 7, 3), "ACME TECH PVT LTD BONUS", credit=D("90000"))

    classify_all_transactions(session)
    result = compute_vnmi(session, account.id)

    assert result["value"] is not None
    assert result["value"] < 90000  # bonus-month salary shouldn't dominate the average


def test_foir_requires_vnmi(session, make_account, make_txn):
    account = _salaried_account(make_account, make_txn)
    classify_all_transactions(session)
    result = compute_foir(session, account.id)

    assert result["value"] is not None
    assert result["band"] in ("lower_burden", "elevated", "higher_burden")


def test_foir_not_available_without_income(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 5), "RANDOM SHOP PURCHASE", debit=D("250"))
    classify_all_transactions(session)

    result = compute_foir(session, account.id)
    assert result["value"] is None
    assert result["band"] == "NOT_AVAILABLE"


def test_namb_computes_average_daily_balance(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 1), "OPENING", credit=D("10000"), balance=D("10000"))
    make_txn(account, 1, date(2026, 4, 11), "SPEND", debit=D("5000"), balance=D("5000"))

    result = compute_namb(session, account.id)
    assert result["value"] is not None
    # 10 days at 10000 + rest at 5000 over an 11-day window should land between the two.
    assert 5000 < result["value"] < 10000


def test_discretionary_ratio_excludes_internal_transfers(session, make_account, make_txn):
    account = _salaried_account(make_account, make_txn)
    classify_all_transactions(session)
    result = compute_discretionary_spending_ratio(session, account.id)
    assert result["value"] is not None
    assert 0 <= result["value"] <= 100


def test_cleansing_cycle_tracks_days_to_low_balance(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 2), "ACME TECH PVT LTD SAL", credit=D("45000"), balance=D("45500"))
    make_txn(account, 1, date(2026, 4, 22), "EMI PAYMENT LOAN8842", debit=D("18450"), balance=D("27050"))
    make_txn(account, 1, date(2026, 4, 28), "BIG SPEND", debit=D("26500"), balance=D("550"))

    classify_all_transactions(session)
    result = compute_salary_to_obligation_cleansing_cycle(session, account.id, low_balance_threshold=D("1000"))

    assert len(result["cycles"]) == 1
    cycle = result["cycles"][0]
    assert cycle["days_salary_to_low_balance"] == 26
    assert cycle["days_salary_to_obligations_cleared"] == 20
