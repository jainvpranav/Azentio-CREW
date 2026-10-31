"""Statement reconciliation - verify opening + txns = closing"""
from decimal import Decimal
from typing import List, Tuple
from sqlmodel import Session, select

from app.models import Statement, Transaction


def reconcile_statement(session: Session, statement_id: int) -> dict:
    """
    Reconcile statement: opening_balance + credits - debits == closing_balance
    Checks both statement-level and row-level balances.

    Returns:
        {
            "reconciled": bool,
            "discrepancy": Decimal | None,
            "discrepancy_rows": list of {row_id, expected, actual, diff}
        }
    """
    statement = session.get(Statement, statement_id)
    if not statement:
        return {"error": "Statement not found"}

    # Get all transactions for this statement, in order
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.statement_id == statement_id)
        .order_by(Transaction.txn_date, Transaction.row_index)
    ).all()

    # Statement-level reconciliation
    total_credits = sum(t.credit or Decimal(0) for t in transactions)
    total_debits = sum(t.debit or Decimal(0) for t in transactions)
    computed_closing = statement.opening_balance + total_credits - total_debits

    # Allow small tolerance for rounding
    tolerance = Decimal("0.01")
    discrepancy = abs(computed_closing - statement.closing_balance)
    reconciled = discrepancy <= tolerance

    # Store results
    statement.computed_closing = computed_closing
    statement.reconciled = reconciled
    statement.discrepancy = discrepancy if not reconciled else None

    # Row-level reconciliation (running balance check)
    discrepancy_rows = []
    running_balance = statement.opening_balance

    for idx, txn in enumerate(transactions):
        expected_balance = running_balance + (txn.credit or Decimal(0)) - (txn.debit or Decimal(0))
        actual_balance = txn.balance

        if actual_balance and abs(expected_balance - actual_balance) > tolerance:
            discrepancy_rows.append({
                "txn_id": txn.id,
                "row_index": txn.row_index,
                "expected": float(expected_balance),
                "actual": float(actual_balance),
                "difference": float(expected_balance - actual_balance),
            })

        if actual_balance:
            running_balance = actual_balance

    if discrepancy_rows:
        import json
        statement.discrepancy_rows = json.dumps(discrepancy_rows)

    session.add(statement)
    session.commit()

    return {
        "reconciled": reconciled,
        "statement_id": statement_id,
        "opening_balance": float(statement.opening_balance),
        "closing_balance": float(statement.closing_balance),
        "computed_closing": float(computed_closing),
        "discrepancy": float(discrepancy) if discrepancy > 0 else 0,
        "discrepancy_rows": discrepancy_rows,
    }
