"""Data quality and review flags"""
import json
from decimal import Decimal
from sqlmodel import Session, select

from app.models import Transaction, Statement, Flag, FlagSeverity, Classification, TransactionCategory, Account


def create_flag(
    session: Session,
    flag_type: str,
    severity: FlagSeverity,
    message: str,
    txn_id: int = None,
    statement_id: int = None,
    account_id: int = None,
    evidence: list = None
) -> Flag:
    """Create a flag"""
    flag = Flag(
        txn_id=txn_id,
        statement_id=statement_id,
        account_id=account_id,
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
                account_id=statement.account_id,
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

    accounts = set(t.account_id for t in duplicates)
    for account_id in accounts:
        dup_ids = [t.id for t in duplicates if t.account_id == account_id]
        create_flag(
            session,
            "DUPLICATES_REMOVED",
            FlagSeverity.INFO,
            f"Found and deduplicated {len(dup_ids)} transactions.",
            account_id=account_id,
            evidence=dup_ids
        )

    session.commit()
    return {"flags_created": len(accounts), "type": "DUPLICATES_REMOVED"}


def check_large_cash_deposits(session: Session) -> dict:
    """Flag cash deposits > 2x the account's median monthly income, or > Rs.2L"""
    from app.pipeline.metrics import compute_metric_detail

    accounts = session.exec(select(Account)).all()
    count = 0
    for account in accounts:
        income = compute_metric_detail(session, account.id, "income")
        median_income = Decimal(str(income["value"])) if income["value"] else None

        txns = session.exec(
            select(Transaction)
            .where(Transaction.account_id == account.id)
            .where(Transaction.credit != None)
        ).all()
        for txn in txns:
            if "CASH" not in txn.description.upper() and "CDM" not in txn.description.upper():
                continue
            if txn.credit > Decimal("200000") or (median_income and txn.credit > median_income * 2):
                create_flag(
                    session,
                    "LARGE_CASH_DEPOSIT",
                    FlagSeverity.WARN,
                    f"Large cash deposit: ₹{txn.credit}. Requires review.",
                    txn_id=txn.id,
                    account_id=account.id,
                    evidence=[txn.id]
                )
                count += 1

    session.commit()
    return {"flags_created": count, "type": "LARGE_CASH_DEPOSIT"}


def check_round_figures(session: Session) -> dict:
    """Flag round-figure (multiple of 10,000) credits in the last 30 days of an account's coverage"""
    from datetime import timedelta

    accounts = session.exec(select(Account)).all()
    count = 0
    for account in accounts:
        txns = session.exec(
            select(Transaction)
            .where(Transaction.account_id == account.id)
            .where(Transaction.credit != None)
        ).all()
        if not txns:
            continue
        max_date = max(t.txn_date for t in txns)
        window_start = max_date - timedelta(days=30)

        for txn in txns:
            if txn.txn_date < window_start:
                continue
            if txn.credit % Decimal("10000") == 0 and txn.credit > Decimal("10000"):
                create_flag(
                    session,
                    "ROUND_FIGURE_SPIKE",
                    FlagSeverity.WARN,
                    f"Round figure credit: ₹{txn.credit}. May need review.",
                    txn_id=txn.id,
                    account_id=account.id,
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
                    account_id=txn.account_id,
                    evidence=[txn.id]
                )
                count += 1

    session.commit()
    return {"flags_created": count, "type": "RETURNED_PAYMENT"}


def check_missing_months(session: Session) -> dict:
    """Flag accounts with missing-coverage months"""
    from app.pipeline.coverage import get_month_coverage

    accounts = session.exec(select(Account)).all()
    count = 0
    for account in accounts:
        coverage = get_month_coverage(session, account.id)
        missing = [m for m, s in coverage["coverage_grid"].items() if s == "missing"]
        if missing:
            create_flag(
                session,
                "MISSING_MONTH",
                FlagSeverity.WARN,
                f"No statement coverage for: {', '.join(missing)}. Not counted as zero in any metric.",
                account_id=account.id,
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "MISSING_MONTH"}


def check_low_balance(session: Session) -> dict:
    """Flag months with >=5 days below the low-balance threshold (carry-forward balance)"""
    from app.pipeline.metrics import compute_balance_trend

    accounts = session.exec(select(Account)).all()
    count = 0
    for account in accounts:
        trend = compute_balance_trend(session, account.id)
        for month, days in trend["days_below_threshold"].items():
            if days >= 5:
                create_flag(
                    session,
                    "LOW_BALANCE",
                    FlagSeverity.WARN,
                    f"{days} days below ₹{trend['threshold']:.0f} balance in {month}.",
                    account_id=account.id,
                )
                count += 1

    session.commit()
    return {"flags_created": count, "type": "LOW_BALANCE"}


def check_income_decline(session: Session) -> dict:
    """Flag accounts where the last 3 months' income is <70% of the prior 3 months'"""
    from app.pipeline.metrics import compute_metric_detail

    accounts = session.exec(select(Account)).all()
    count = 0
    for account in accounts:
        detail = compute_metric_detail(session, account.id, "income")
        months = sorted(detail["by_month"].keys())
        if len(months) < 6:
            continue
        prior_3 = sum(detail["by_month"][m] for m in months[-6:-3])
        last_3 = sum(detail["by_month"][m] for m in months[-3:])
        if prior_3 > 0 and last_3 < 0.7 * prior_3:
            create_flag(
                session,
                "INCOME_DECLINE",
                FlagSeverity.WARN,
                f"Last 3 months' income (₹{last_3:.0f}) is below 70% of the prior 3 months' (₹{prior_3:.0f}).",
                account_id=account.id,
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "INCOME_DECLINE"}


def generate_all_flags(session: Session) -> dict:
    """Run all flag checks. Re-running clears previously generated flags first (idempotent)."""
    for flag in session.exec(select(Flag)).all():
        session.delete(flag)
    session.commit()

    results = {
        "reconciliation": check_reconciliation_mismatches(session),
        "duplicates": check_duplicates(session),
        "large_deposits": check_large_cash_deposits(session),
        "round_figures": check_round_figures(session),
        "returned": check_returned_payments(session),
        "missing_months": check_missing_months(session),
        "low_balance": check_low_balance(session),
        "income_decline": check_income_decline(session),
    }

    total_flags = session.exec(select(Flag)).all()

    return {
        "total_flags": len(total_flags),
        "checks": results,
    }


def get_flag_queue(session: Session) -> dict:
    """Get all flags sorted by severity, with transaction/statement context for display."""
    flags = session.exec(select(Flag)).all()

    by_severity = {
        "high": [],
        "warn": [],
        "info": [],
    }

    for flag in flags:
        context = {}
        if flag.txn_id:
            txn = session.get(Transaction, flag.txn_id)
            if txn:
                context = {
                    "txn_date": txn.txn_date.isoformat(),
                    "description": txn.description,
                    "amount": float(txn.credit or txn.debit or 0),
                }
        elif flag.statement_id:
            stmt = session.get(Statement, flag.statement_id)
            if stmt:
                context = {
                    "period_start": stmt.period_start.isoformat(),
                    "period_end": stmt.period_end.isoformat(),
                }

        severity_key = flag.severity.value.lower()
        by_severity[severity_key].append({
            "id": flag.id,
            "type": flag.flag_type,
            "message": flag.message,
            "txn_id": flag.txn_id,
            "statement_id": flag.statement_id,
            "context": context,
        })

    return {
        "total": len(flags),
        "by_severity": by_severity,
    }
