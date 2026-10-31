from datetime import date
from decimal import Decimal as D

from app.pipeline.classify import classify_all_transactions
from app.pipeline.flags import generate_all_flags
from app.pipeline.reports import build_individual_report, build_sme_report


def test_individual_report_has_required_sections(session, make_account, make_txn):
    account = make_account()
    for month, day in [(4, 2), (5, 2), (6, 2)]:
        make_txn(account, 1, date(2026, month, day), "ACME TECH PVT LTD SAL", credit=D("45000"))
        make_txn(account, 1, date(2026, month, day + 5), "EMI PAYMENT LOAN8842", debit=D("10000"))
    classify_all_transactions(session)
    generate_all_flags(session)

    report = build_individual_report(session, account.id)

    assert report["report_type"] == "INDIVIDUAL"
    for key in ("vnmi", "namb", "foir", "salary_to_obligation_cleansing_cycle", "discretionary_spending_ratio"):
        assert key in report["metrics"]
    assert "red_flags" in report and "category_anomalies" in report and "ai_reviewer_findings" in report
    assert "fraud" not in report["disclaimer"].lower() or "does not assert fraud" in report["disclaimer"].lower()


def test_sme_report_has_required_sections(session, make_account, make_txn):
    account = make_account(holder_name="ACME TRADERS")
    make_txn(account, 1, date(2026, 4, 5), "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
    make_txn(account, 1, date(2026, 5, 20), "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
    classify_all_transactions(session)

    report = build_sme_report(session, account.id)

    assert report["report_type"] == "SME"
    for key in ("gbt", "dscr", "customer_concentration", "cc_od_utilization", "trade_inflow_outflow_ratio"):
        assert key in report["metrics"]
    assert "customer_receipts" in report
