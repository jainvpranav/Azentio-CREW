from datetime import date
from decimal import Decimal as D

from app.models import Customer, EntityType
from app.pipeline.classify import classify_all_transactions
from app.pipeline.rules_engine import evaluate_individual, evaluate_sme, evaluate_account, resolve_entity_type


def test_evaluate_individual_produces_indicators_with_audit_rows(session, make_account, make_txn):
    from app.models import RuleEvaluation
    from sqlmodel import select

    account = make_account()
    for month, day in [(4, 2), (5, 2), (6, 2)]:
        make_txn(account, 1, date(2026, month, day), "ACME TECH PVT LTD SAL", credit=D("45000"))
        make_txn(account, 1, date(2026, month, day + 5), "EMI PAYMENT LOAN8842", debit=D("30000"))
    classify_all_transactions(session)

    result = evaluate_individual(session, account.id)

    assert result["entity_type"] == "INDIVIDUAL"
    rule_ids = {i["rule_id"] for i in result["indicators"]}
    assert "Rule_Ind_FOIR" in rule_ids
    assert result["review_priority"] in ("lower_review_priority", "elevated", "higher_review_priority")

    rows = session.exec(select(RuleEvaluation).where(RuleEvaluation.account_id == account.id)).all()
    assert len(rows) == len(result["indicators"])
    assert all(r.rule_version for r in rows)


def test_evaluate_sme_handles_missing_cc_od_metadata(session, make_account, make_txn):
    account = make_account(holder_name="ACME TRADERS")
    make_txn(account, 1, date(2026, 4, 5), "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
    make_txn(account, 1, date(2026, 5, 20), "UPI/BIGCUSTOMER/PAYMENT", credit=D("200000"))
    classify_all_transactions(session)

    result = evaluate_sme(session, account.id)
    cc_od_indicator = next(i for i in result["indicators"] if i["rule_id"] == "Rule_SME_CCOD")
    assert cc_od_indicator["result"] == "NOT_AVAILABLE"
    assert cc_od_indicator["confidence"] == "missing_metadata"


def test_evaluate_account_routes_by_entity_type(session, make_account, make_txn):
    account = make_account()
    customer = Customer(name="Test SME Co", entity_type=EntityType.SME)
    session.add(customer)
    session.commit()
    session.refresh(customer)
    account.customer_id = customer.id
    session.add(account)
    session.commit()

    assert resolve_entity_type(session, account.id) == EntityType.SME
    result = evaluate_account(session, account.id)
    assert result["entity_type"] == "SME"
