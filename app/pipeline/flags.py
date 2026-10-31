"""Data quality and review flags"""
import json
from decimal import Decimal
from sqlmodel import Session, select

from app.models import Transaction, Statement, Flag, FlagSeverity, Classification, TransactionCategory


def create_flag(
    session: Session,
    flag_type: str,
    severity: FlagSeverity,
    message: str,
    txn_id: int = None,
    statement_id: int = None,
    evidence: list = None
) -> Flag:
    """Create a flag"""
    flag = Flag(
        txn_id=txn_id,
        statement_id=statement_id,
        flag_type=flag_type,
        severity=severity,
        message=message,
        evidence=json.dumps(evidence) if evidence else None,
    )
    session.add(flag)
    return flag


def check_reconciliation_mismatches(session: Session) -> dict:
    """Flag statements with reconciliation mismatches"""
    statements = session.exec(
        select(Statement).where(Statement.reconciled == False)
    ).all()

    count = 0
    for statement in statements:
        if statement.discrepancy and statement.discrepancy > Decimal("0.01"):
            create_flag(
                session,
                "RECON_MISMATCH",
                FlagSeverity.HIGH,
                f"Statement mismatch: ₹{statement.discrepancy}. Opening + txns ≠ closing.",
                statement_id=statement.id,
                evidence=[statement.id]
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "RECON_MISMATCH"}


def check_duplicates(session: Session) -> dict:
    """Flag accounts with duplicate transactions"""
    duplicates = session.exec(
        select(Transaction).where(Transaction.duplicate_of != None)
    ).all()

    if duplicates:
        accounts = set(t.account_id for t in duplicates)
        for account_id in accounts:
            dup_ids = [t.id for t in duplicates if t.account_id == account_id]
            create_flag(
                session,
                "DUPLICATES_REMOVED",
                FlagSeverity.INFO,
                f"Found and deduplicated {len(dup_ids)} transactions.",
                evidence=dup_ids
            )

    session.commit()
    return {"flags_created": len(accounts), "type": "DUPLICATES_REMOVED"}


def check_large_cash_deposits(session: Session) -> dict:
    """Flag unusually large cash deposits"""
    # Get all cash deposits
    cash_deposits = session.exec(
        select(Transaction)
        .where(Transaction.credit != None)
    ).all()

    # Filter for cash deposits
    cash_txns = []
    for txn in cash_deposits:
        if "CASH" in txn.description.upper() or "CDM" in txn.description.upper():
            cash_txns.append(txn)

    count = 0
    for txn in cash_txns:
        # Flag if > 2L or unusual
        if txn.credit > Decimal("200000"):
            create_flag(
                session,
                "LARGE_CASH_DEPOSIT",
                FlagSeverity.WARN,
                f"Large cash deposit: ₹{txn.credit}. Requires review.",
                txn_id=txn.id,
                evidence=[txn.id]
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "LARGE_CASH_DEPOSIT"}


def check_round_figures(session: Session) -> dict:
    """Flag round-figure credits (potential transfers)"""
    transactions = session.exec(
        select(Transaction).where(Transaction.credit != None)
    ).all()

    count = 0
    for txn in transactions:
        # Check if amount is multiple of 10,000
        if txn.credit % Decimal("10000") == 0 and txn.credit > Decimal("10000"):
            create_flag(
                session,
                "ROUND_FIGURE_SPIKE",
                FlagSeverity.WARN,
                f"Round figure credit: ₹{txn.credit}. May need review.",
                txn_id=txn.id,
                evidence=[txn.id]
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "ROUND_FIGURE_SPIKE"}


def check_returned_payments(session: Session) -> dict:
    """Flag any returned/bounced payments"""
    transactions = session.exec(
        select(Transaction)
    ).all()

    count = 0
    for txn in transactions:
        if "RETURN" in txn.description.upper() or "BOUNCE" in txn.description.upper():
            classification = session.exec(
                select(Classification)
                .where(Classification.txn_id == txn.id)
                .where(Classification.is_current == True)
            ).first()

            if classification and classification.category == TransactionCategory.RETURNED_PAYMENT:
                create_flag(
                    session,
                    "RETURNED_PAYMENT",
                    FlagSeverity.HIGH,
                    "Payment returned or bounced. Requires investigation.",
                    txn_id=txn.id,
                    evidence=[txn.id]
                )
                count += 1

    session.commit()
    return {"flags_created": count, "type": "RETURNED_PAYMENT"}


def generate_all_flags(session: Session) -> dict:
    """Run all flag checks"""
    results = {
        "reconciliation": check_reconciliation_mismatches(session),
        "duplicates": check_duplicates(session),
        "large_deposits": check_large_cash_deposits(session),
        "round_figures": check_round_figures(session),
        "returned": check_returned_payments(session),
    }

    total_flags = session.exec(select(Flag)).all()

    return {
        "total_flags": len(total_flags),
        "checks": results,
    }


def get_flag_queue(session: Session) -> dict:
    """Get all flags sorted by severity"""
    flags = session.exec(select(Flag)).all()

    by_severity = {
        "high": [],
        "warn": [],
        "info": [],
    }

    for flag in flags:
        severity_key = flag.severity.value.lower()
        by_severity[severity_key].append({
            "id": flag.id,
            "type": flag.flag_type,
            "message": flag.message,
            "txn_id": flag.txn_id,
            "statement_id": flag.statement_id,
        })

    return {
        "total": len(flags),
        "by_severity": by_severity,
    }
