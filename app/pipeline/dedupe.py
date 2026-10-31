"""Deduplication - find and mark duplicate transactions"""
import hashlib
from decimal import Decimal
from sqlmodel import Session, select

from app.models import Transaction, Account


def compute_fingerprint(
    account_id: int,
    txn_date,
    debit,
    credit,
    balance,
    description: str
) -> str:
    """
    Compute transaction fingerprint for dedup.
    Fingerprint = hash(account_id, date, debit, credit, balance, desc[:40])
    """
    # Normalize amounts to 2 decimals
    debit_str = f"{debit:.2f}" if debit else "0.00"
    credit_str = f"{credit:.2f}" if credit else "0.00"
    balance_str = f"{balance:.2f}" if balance else "0.00"

    data = f"{account_id}|{txn_date}|{debit_str}|{credit_str}|{balance_str}|{description[:40]}"
    return hashlib.md5(data.encode()).hexdigest()


def deduplicate_account(session: Session, account_id: int) -> dict:
    """
    Mark duplicate transactions within an account.
    Handles overlapping statements (keep first, mark others as duplicates).

    Returns:
        {
            "account_id": int,
            "duplicates_found": int,
            "removed_ids": list[int]
        }
    """
    # Get all transactions for account, ordered by date + row_index
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.txn_date, Transaction.row_index)
    ).all()

    seen_fingerprints = {}
    removed_ids = []

    for txn in transactions:
        if txn.duplicate_of:
            # Already marked
            continue

        fingerprint = compute_fingerprint(
            account_id,
            txn.txn_date,
            txn.debit,
            txn.credit,
            txn.balance,
            txn.description,
        )
        txn.fingerprint = fingerprint

        if fingerprint in seen_fingerprints:
            # Duplicate! Mark it
            original_txn_id = seen_fingerprints[fingerprint]
            txn.duplicate_of = original_txn_id
            removed_ids.append(txn.id)
        else:
            # First occurrence
            seen_fingerprints[fingerprint] = txn.id

        session.add(txn)

    session.commit()

    return {
        "account_id": account_id,
        "duplicates_found": len(removed_ids),
        "removed_ids": removed_ids,
    }


def deduplicate_all(session: Session) -> dict:
    """Run deduplication for all accounts"""
    accounts = session.exec(select(Account)).all()

    results = {
        "total_duplicates": 0,
        "by_account": [],
    }

    for account in accounts:
        result = deduplicate_account(session, account.id)
        results["by_account"].append(result)
        results["total_duplicates"] += result["duplicates_found"]

    return results
