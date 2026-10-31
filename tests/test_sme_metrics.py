from datetime import date
from decimal import Decimal as D

from app.models import Facility
from app.pipeline.classify import classify_all_transactions
from app.pipeline.sme_metrics import (
    compute_gbt, compute_dscr, compute_customer_concentration,
    compute_cc_od_utilization, compute_trade_inflow_outflow_ratio,
)


def _sme_account(make_account, make_txn):
    account = make_account(account_number="SME001", holder_name="ACME TRADERS")
    # BIGCUSTOMER days are irregular (not ~monthly, not same day-of-month) so
    # find_salary_clusters() doesn't mistake repeat B2B receipts for a
    # payroll cluster; recurrence (count>=2) still makes BIZ_RECEIPT fire.
    big_customer_dates = [date(2026, 4, 5), date(2026, 5, 20), date(2026, 6, 2)]
    for i, d in enumerate(big_customer_dates):
        make_txn(account, 1, d, "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
        make_txn(account, 1, d, f"UPI/SMALLCUSTOMER{i}/PAYMENT", credit=D("20000"))
        make_txn(account, 1, d, "SUPPLIER PAYMENT RENT", debit=D("15000"))
        make_txn(account, 1, d, "EMI PAYMENT LOAN9911", debit=D("30000"))
    return account


def test_gbt_only_counts_verified_business_receipts(session, make_account, make_txn):
    account = _sme_account(make_account, make_txn)
    classify_all_transactions(session)
    result = compute_gbt(session, account.id)

    # BIGCUSTOMER recurs (count=3) -> confidently verified BUSINESS_RECEIPT.
    # Each SMALLCUSTOMER-N appears once -> POSSIBLE_BUSINESS_RECEIPT, excluded from GBT.
    assert result["value"] == 3 * 200000
    assert result["unverified_credits_total"] == 3 * 20000


def test_dscr_band_reflects_coverage(session, make_account, make_txn):
    account = _sme_account(make_account, make_txn)
    classify_all_transactions(session)
    result = compute_dscr(session, account.id)

    assert result["value"] is not None
    assert result["band"] in ("possible_shortfall", "adequate_coverage", "strong_coverage")


def test_customer_concentration_top1(session, make_account, make_txn):
    account = _sme_account(make_account, make_txn)
    classify_all_transactions(session)
    result = compute_customer_concentration(session, account.id)

    assert result["top1_share"] > 80  # BIGCUSTOMER dominates verified inflow
    assert result["top1_elevated"] is True


def test_cc_od_utilization_not_available_without_facility(session, make_account, make_txn):
    account = _sme_account(make_account, make_txn)
    classify_all_transactions(session)
    result = compute_cc_od_utilization(session, account.id)

    assert result["value"] == "NOT_AVAILABLE"
    assert "sanctioned_limit" in result["missing_metadata"]


def test_cc_od_utilization_with_facility(session, make_account, make_txn):
    account = make_account(account_number="OD001")
    session.add(Facility(account_id=account.id, facility_type="OD", sanctioned_limit=D("100000")))
    session.commit()

    make_txn(account, 1, date(2026, 4, 1), "OPENING", balance=D("-20000"))
    make_txn(account, 1, date(2026, 4, 11), "REPAY", credit=D("10000"), balance=D("-10000"))

    result = compute_cc_od_utilization(session, account.id)
    assert isinstance(result["value"], float)
    assert 0 < result["value"] < 100


def test_trade_ratio_not_available_without_payables(session, make_account, make_txn):
    account = make_account(account_number="SME002")
    make_txn(account, 1, date(2026, 4, 5), "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
    make_txn(account, 1, date(2026, 5, 5), "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
    classify_all_transactions(session)

    result = compute_trade_inflow_outflow_ratio(session, account.id)
    assert result["value"] == "NOT_AVAILABLE"
