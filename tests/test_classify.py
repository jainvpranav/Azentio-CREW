from datetime import date
from decimal import Decimal as D

from app.models import TransactionCategory
from app.pipeline.classify import classify_all_transactions


def test_classify_all_assigns_expected_categories(session, make_account, make_txn):
    account = make_account()
    salary1 = make_txn(account, 1, date(2026, 4, 2), "ACME TECH PVT LTD SAL APR", credit=D("45000"))
    salary2 = make_txn(account, 1, date(2026, 5, 2), "ACME TECH PVT LTD SAL MAY", credit=D("45000"))
    emi = make_txn(account, 1, date(2026, 4, 22), "EMI PAYMENT LOAN8842", debit=D("18450"))
    atm = make_txn(account, 1, date(2026, 4, 15), "ATM CASH WDL", debit=D("3000"))
    utility = make_txn(account, 1, date(2026, 4, 20), "BESCOM ELECTRICITY BILL", debit=D("1450"))
    misc = make_txn(account, 1, date(2026, 4, 25), "RANDOM SHOP PURCHASE", debit=D("250"))

    classify_all_transactions(session)

    def current_category(txn):
        from app.models import Classification
        from sqlmodel import select
        c = session.exec(
            select(Classification).where(Classification.txn_id == txn.id).where(Classification.is_current == True)
        ).first()
        return c.category

    assert current_category(salary1) == TransactionCategory.SALARY
    assert current_category(salary2) == TransactionCategory.SALARY
    assert current_category(emi) == TransactionCategory.LOAN_EMI
    assert current_category(atm) == TransactionCategory.CASH_WITHDRAWAL
    assert current_category(utility) == TransactionCategory.UTILITIES
    assert current_category(misc) == TransactionCategory.OTHER_EXPENSE


def test_classify_all_is_append_only_on_rerun(session, make_account, make_txn):
    from app.models import Classification
    from sqlmodel import select

    account = make_account()
    txn = make_txn(account, 1, date(2026, 4, 15), "ATM CASH WDL", debit=D("3000"))

    classify_all_transactions(session)
    classify_all_transactions(session)  # re-run should not create a second row

    rows = session.exec(select(Classification).where(Classification.txn_id == txn.id)).all()
    assert len(rows) == 1


def test_classify_cross_account_transfer(session, make_account, make_txn):
    from app.models import Classification
    from sqlmodel import select

    acc_a = make_account(account_number="AAAA1111")
    acc_b = make_account(account_number="BBBB2222")
    debit = make_txn(acc_a, 1, date(2026, 4, 3), "NEFT TO OWN A/C", debit=D("50000"))
    credit = make_txn(acc_b, 2, date(2026, 4, 3), "NEFT CR FROM SELF", credit=D("50000"))

    classify_all_transactions(session)

    for txn in (debit, credit):
        c = session.exec(
            select(Classification).where(Classification.txn_id == txn.id).where(Classification.is_current == True)
        ).first()
        assert c.category == TransactionCategory.INTERNAL_TRANSFER
        assert c.rule_id == "XFER_PAIR"
