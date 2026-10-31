from datetime import date
from decimal import Decimal as D

from app.pipeline.classify import classify_all_transactions
from app.pipeline import anomalies


def test_refund_without_original_is_flagged(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 10), "REFUND FROM UNKNOWN MERCHANT", credit=D("500"))
    classify_all_transactions(session)

    result = anomalies.check_refund_reversal_anomalies(session, account.id)
    assert result["refund_without_original"]["count"] == 1


def test_possible_duplicate_emi_detected(session, make_account, make_txn):
    account = make_account()
    for d in (date(2026, 4, 5), date(2026, 5, 5), date(2026, 5, 8)):
        make_txn(account, 1, d, "EMI PAYMENT LOAN1234", debit=D("10000"))
    classify_all_transactions(session)

    result = anomalies.check_loan_emi_anomalies(session, account.id)
    assert len(result["possible_duplicate_emi"]) == 1


def test_sudden_business_receipt_increase_flagged(session, make_account, make_txn):
    account = make_account(holder_name="ACME TRADERS")
    # Irregular days/gaps so find_salary_clusters() doesn't mistake this
    # repeat B2B counterparty for a payroll cluster (see test_sme_metrics
    # for the same consideration). Three normal months, then a spike.
    for d, amount in [
        (date(2026, 1, 5), 50000), (date(2026, 2, 20), 52000),
        (date(2026, 3, 3), 48000), (date(2026, 4, 15), 200000),
    ]:
        make_txn(account, 1, d, "UPI/BIGCUSTOMER/PAYMENT", credit=D(str(amount)))
    classify_all_transactions(session)

    result = anomalies.check_business_receipt_anomalies(session, account.id)
    assert result["sudden_increase"]["count"] == 1


def test_run_all_does_not_raise_on_sparse_data(session, make_account, make_txn):
    account = make_account()
    make_txn(account, 1, date(2026, 4, 1), "RANDOM SHOP PURCHASE", debit=D("250"))
    classify_all_transactions(session)

    result = anomalies.run_all(session, account.id)
    assert set(result.keys()) == {"internal_transfer", "salary", "business_receipt", "refund_reversal", "loan_emi", "expense"}
