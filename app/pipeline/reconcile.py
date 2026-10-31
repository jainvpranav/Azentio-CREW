"""Statement reconciliation - verify opening + txns = closing, per currency."""
import json
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional
from sqlmodel import Session, select

from app.models import Statement, Transaction


def reconcile_statement(session: Session, statement_id: int) -> dict:
    """
    Reconcile statement: opening_balance + credits - debits == closing_balance.

    Currency isolation: all arithmetic is scoped to the same currency.
    Transactions with unknown/missing currency are excluded from the main
    reconciliation and listed under 'excluded_unknown_currency'.
    Checks both statement-level and row-level running balances.
    """
    statement = session.get(Statement, statement_id)
    if not statement:
        return {"error": "Statement not found"}

    if statement.opening_balance is None or statement.closing_balance is None:
        statement.reconciled = False
        statement.discrepancy = None
        session.add(statement)
        session.commit()
        return {
            "reconciled": False,
            "statement_id": statement_id,
            "opening_balance": None,
            "closing_balance": None,
            "computed_closing": None,
            "discrepancy": None,
            "discrepancy_rows": [],
            "error": "opening_or_closing_balance_unknown",
        }

    transactions = session.exec(
        select(Transaction)
        .where(Transaction.statement_id == statement_id)
        .order_by(Transaction.txn_date, Transaction.row_index)
    ).all()

    # Determine the statement's declared currency (may be None)
    stmt_currency = statement.currency

    # Partition: known-currency vs unknown-currency transactions
    # Only perform arithmetic on transactions whose currency matches the statement
    # currency (or both are None, meaning no currency info at all).
    known_txns: List[Transaction] = []
    excluded_unknown: List[int] = []
    cross_currency: Dict[str, List[int]] = defaultdict(list)

    for t in transactions:
        txn_currency = t.currency
        if stmt_currency is None and txn_currency is None:
            known_txns.append(t)
        elif txn_currency is None:
            excluded_unknown.append(t.id)
        elif stmt_currency is None or txn_currency == stmt_currency:
            known_txns.append(t)
        else:
            # Different currency — do not mix
            cross_currency[txn_currency].append(t.id)

    tolerance = Decimal("0.01")

    # Statement-level reconciliation on same-currency transactions only
    total_credits = sum(t.credit or Decimal(0) for t in known_txns)
    total_debits = sum(t.debit or Decimal(0) for t in known_txns)
    computed_closing = statement.opening_balance + total_credits - total_debits

    discrepancy = abs(computed_closing - statement.closing_balance)
    reconciled = discrepancy <= tolerance

    # Row-level running balance check
    discrepancy_rows = []
    running_balance = statement.opening_balance

    for txn in known_txns:
        expected_balance = running_balance + (txn.credit or Decimal(0)) - (txn.debit or Decimal(0))
        actual_balance = txn.balance

        if actual_balance and abs(expected_balance - actual_balance) > tolerance:
            discrepancy_rows.append({
                "txn_id": txn.id,
                "row_index": txn.row_index,
                "expected": float(expected_balance),
                "actual": float(actual_balance),
                "difference": float(expected_balance - actual_balance),
                "currency": txn.currency,
            })

        if actual_balance:
            running_balance = actual_balance

    statement.computed_closing = computed_closing
    statement.reconciled = reconciled
    statement.discrepancy = discrepancy if not reconciled else None
    if discrepancy_rows:
        statement.discrepancy_rows = json.dumps(discrepancy_rows)
    session.add(statement)
    session.commit()

    result = {
        "reconciled": reconciled,
        "statement_id": statement_id,
        "currency": stmt_currency,
        "opening_balance": float(statement.opening_balance),
        "closing_balance": float(statement.closing_balance),
        "computed_closing": float(computed_closing),
        "discrepancy": float(discrepancy) if discrepancy > 0 else 0,
        "discrepancy_rows": discrepancy_rows,
    }

    if excluded_unknown:
        result["excluded_unknown_currency"] = excluded_unknown
        result["reconciliation_limitation"] = (
            f"{len(excluded_unknown)} transaction(s) with no determinable currency "
            "were excluded from this calculation."
        )

    if cross_currency:
        result["cross_currency_transactions"] = {
            ccy: ids for ccy, ids in cross_currency.items()
        }
        result["reconciliation_limitation"] = (
            result.get("reconciliation_limitation", "")
            + f" {sum(len(v) for v in cross_currency.values())} transaction(s) "
            "in other currencies were not included in this reconciliation."
        ).strip()

    return result
