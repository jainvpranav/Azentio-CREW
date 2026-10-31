from datetime import date
from decimal import Decimal

from app import models
from app.pipeline.reconcile import reconcile_statement


def _make_statement(session, account, opening, closing, period_start, period_end):
    stmt = models.Statement(
        document_id=1, account_id=account.id,
        period_start=period_start, period_end=period_end,
        opening_balance=opening, closing_balance=closing,
    )
    session.add(stmt)
    session.commit()
    session.refresh(stmt)
    return stmt


def test_reconcile_matches_when_balanced(session, make_account, make_txn):
    account = make_account()
    stmt = _make_statement(session, account, Decimal("1000"), Decimal("1500"), date(2026, 1, 1), date(2026, 1, 31))
    make_txn(account, stmt.id, date(2026, 1, 5), "CREDIT", credit=Decimal("1000"), balance=Decimal("2000"))
    make_txn(account, stmt.id, date(2026, 1, 10), "DEBIT", debit=Decimal("500"), balance=Decimal("1500"))

    result = reconcile_statement(session, stmt.id)
    assert result["reconciled"] is True
    assert result["discrepancy_rows"] == []


def test_reconcile_flags_the_exact_broken_row(session, make_account, make_txn):
    account = make_account()
    stmt = _make_statement(session, account, Decimal("1000"), Decimal("1600"), date(2026, 1, 1), date(2026, 1, 31))
    make_txn(account, stmt.id, date(2026, 1, 5), "CREDIT", credit=Decimal("1000"), balance=Decimal("2000"))
    # This row's printed balance is wrong by 100 (should be 1500)
    make_txn(account, stmt.id, date(2026, 1, 10), "DEBIT", debit=Decimal("500"), balance=Decimal("1600"))

    result = reconcile_statement(session, stmt.id)
    assert result["reconciled"] is False
    assert len(result["discrepancy_rows"]) == 1
    assert result["discrepancy_rows"][0]["difference"] == -100.0


def test_reconcile_handles_unknown_balance_gracefully(session, make_account):
    account = make_account()
    stmt = _make_statement(session, account, None, None, date(2026, 1, 1), date(2026, 1, 31))
    result = reconcile_statement(session, stmt.id)
    assert result["reconciled"] is False
    assert "error" in result
