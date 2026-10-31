from datetime import date
from decimal import Decimal

from app.pipeline.dedupe import deduplicate_account


def test_overlapping_statement_marks_second_occurrence_as_duplicate(session, make_account, make_txn):
    account = make_account()
    t1 = make_txn(account, statement_id=1, txn_date=date(2026, 6, 2), description="SALARY",
                   credit=Decimal("45000"), balance=Decimal("50000"), document_id=1)
    t2 = make_txn(account, statement_id=2, txn_date=date(2026, 6, 2), description="SALARY",
                   credit=Decimal("45000"), balance=Decimal("50000"), document_id=2)

    result = deduplicate_account(session, account.id)

    assert result["duplicates_found"] == 1
    session.refresh(t1)
    session.refresh(t2)
    # Exactly one of the two is marked as the duplicate of the other
    marked = [t for t in (t1, t2) if t.duplicate_of is not None]
    assert len(marked) == 1


def test_different_amounts_on_same_day_are_not_duplicates(session, make_account, make_txn):
    account = make_account()
    make_txn(account, statement_id=1, txn_date=date(2026, 6, 2), description="PAYMENT A",
             debit=Decimal("100"), balance=Decimal("900"))
    make_txn(account, statement_id=1, txn_date=date(2026, 6, 2), description="PAYMENT B",
             debit=Decimal("200"), balance=Decimal("700"))

    result = deduplicate_account(session, account.id)
    assert result["duplicates_found"] == 0
