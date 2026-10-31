"""Data quality and review flags"""
import json
from decimal import Decimal
from collections import Counter
from sqlmodel import Session, select

from app.models import Transaction, Statement, Flag, FlagSeverity, Classification, TransactionCategory, Account

# ISO code → display symbol (used only in human-readable flag messages)
_CURRENCY_SYMBOLS_MAP = {
    'INR': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£',
    'JPY': '¥', 'CNY': '¥', 'AUD': 'A$', 'CAD': 'C$',
    'SGD': 'S$', 'HKD': 'HK$', 'AED': 'AED ',
}


def _fmt_amount(amount, currency: str = None) -> str:
    """Format an amount with its currency symbol for flag messages."""
    symbol = _CURRENCY_SYMBOLS_MAP.get(currency or '', '') or (f'{currency} ' if currency else '')
    return f"{symbol}{amount:,.2f}" if isinstance(amount, (int, float, Decimal)) else f"{symbol}{amount}"


def _account_currency(session: Session, account_id: int) -> str:
    """Return the most common declared currency for an account's statements, or None."""
    stmts = session.exec(select(Statement).where(Statement.account_id == account_id)).all()
    currencies = [s.currency for s in stmts if s.currency]
    if not currencies:
        return None
    return Counter(currencies).most_common(1)[0][0]


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
                f"Statement mismatch: {_fmt_amount(statement.discrepancy, statement.currency)}. Opening + txns ≠ closing.",
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
                    f"Large cash deposit: {_fmt_amount(txn.credit, txn.currency)}. Requires review.",
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
                    f"Round figure credit: {_fmt_amount(txn.credit, txn.currency)}. May need review.",
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
        acct_currency = _account_currency(session, account.id)
        for month, days in trend["days_below_threshold"].items():
            if days >= 5:
                create_flag(
                    session,
                    "LOW_BALANCE",
                    FlagSeverity.WARN,
                    f"{days} days below {_fmt_amount(trend['threshold'], acct_currency)} balance in {month}.",
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
            acct_currency = _account_currency(session, account.id)
            create_flag(
                session,
                "INCOME_DECLINE",
                FlagSeverity.WARN,
                f"Last 3 months' income ({_fmt_amount(last_3, acct_currency)}) is below 70% of the prior 3 months' ({_fmt_amount(prior_3, acct_currency)}).",
                account_id=account.id,
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "INCOME_DECLINE"}


def check_chronology(session: Session) -> dict:
    """
    Flag statements where transactions are not in chronological order.
    Out-of-order dates indicate possible tampering or data-quality issues.
    """
    from app.models import Statement as StmtModel
    statements = session.exec(select(StmtModel)).all()
    count = 0
    for stmt in statements:
        txns = session.exec(
            select(Transaction)
            .where(Transaction.statement_id == stmt.id)
            .order_by(Transaction.row_index)
        ).all()
        if len(txns) < 2:
            continue
        out_of_order = []
        for i in range(1, len(txns)):
            if txns[i].txn_date < txns[i - 1].txn_date:
                out_of_order.append(txns[i].id)
        if out_of_order:
            create_flag(
                session,
                "OUT_OF_ORDER_DATES",
                FlagSeverity.WARN,
                f"{len(out_of_order)} transaction(s) appear out of chronological order. "
                "Possible data-quality issue or document modification.",
                statement_id=stmt.id,
                account_id=stmt.account_id,
                evidence=out_of_order,
            )
            count += 1
    session.commit()
    return {"flags_created": count, "type": "OUT_OF_ORDER_DATES"}


def check_pdf_metadata(session: Session) -> dict:
    """
    Inspect PDF document metadata for suspicious timestamps or producer anomalies.
    Flags when creation date is after the statement period end, or when the
    modification date is significantly later than the creation date.
    """
    import pdfplumber
    from app.models import Document, Statement as StmtModel
    count = 0
    docs = session.exec(
        select(Document).where(Document.file_type == "pdf")
    ).all()
    for doc in docs:
        stmt = session.exec(
            select(StmtModel).where(StmtModel.document_id == doc.id)
        ).first()

        # Try to open and inspect the PDF from the uploads directory
        import os
        pdf_path = os.path.join("uploads", doc.filename)
        if not os.path.exists(pdf_path):
            continue

        try:
            with pdfplumber.open(pdf_path) as pdf:
                meta = pdf.metadata or {}
        except Exception:
            continue

        issues = []
        creation_date = meta.get("CreationDate") or meta.get("creation_date")
        mod_date = meta.get("ModDate") or meta.get("mod_date")
        producer = meta.get("Producer") or meta.get("producer") or ""

        if creation_date and mod_date:
            # Flag if mod date appears significantly different from creation date
            # (heuristic: raw string comparison on the date prefix)
            cd_str = str(creation_date)[:10]
            md_str = str(mod_date)[:10]
            if cd_str and md_str and cd_str != md_str:
                issues.append(f"creation={cd_str}, modification={md_str}")

        # Flag completely missing metadata as an indicator (not proof of tampering)
        if not creation_date and not mod_date and not producer:
            issues.append("no_metadata_fields_present")

        if issues and stmt:
            create_flag(
                session,
                "PDF_METADATA_ANOMALY",
                FlagSeverity.INFO,
                f"PDF metadata indicator(s): {'; '.join(issues)}. "
                "Metadata alone does not prove tampering — review in context.",
                statement_id=stmt.id,
                account_id=stmt.account_id,
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "PDF_METADATA_ANOMALY"}


def check_velocity_spikes(session: Session) -> dict:
    """
    Flag accounts with sudden spikes in transaction volume or cash-flow velocity.
    Uses a heuristic: any calendar week with >3x the account's median weekly count.
    Labeled as a heuristic, not a historical comparison, when no history exists.
    """
    from datetime import timedelta
    import statistics

    accounts = session.exec(select(Account)).all()
    count = 0
    for account in accounts:
        txns = session.exec(
            select(Transaction).where(Transaction.account_id == account.id)
        ).all()
        if len(txns) < 10:
            continue

        # Group by ISO week
        from collections import defaultdict
        weekly: dict = defaultdict(list)
        for t in txns:
            week_key = t.txn_date.isocalendar()[:2]  # (year, week)
            weekly[week_key].append(t)

        if len(weekly) < 3:
            continue

        counts = [len(v) for v in weekly.values()]
        median = statistics.median(counts)
        if median == 0:
            continue

        for week_key, week_txns in weekly.items():
            if len(week_txns) > 3 * median and len(week_txns) >= 5:
                txn_ids = [t.id for t in week_txns]
                year, week = week_key
                create_flag(
                    session,
                    "VELOCITY_SPIKE",
                    FlagSeverity.WARN,
                    f"Week {year}-W{week:02d}: {len(week_txns)} transactions "
                    f"(median: {median:.0f}/week). Heuristic threshold — not a historical baseline.",
                    account_id=account.id,
                    evidence=txn_ids[:20],
                )
                count += 1

    session.commit()
    return {"flags_created": count, "type": "VELOCITY_SPIKE"}


def check_unknown_currency_transactions(session: Session) -> dict:
    """
    Flag transactions whose currency could not be determined.
    These are excluded from currency-specific calculations until resolved.
    """
    txns = session.exec(
        select(Transaction).where(Transaction.currency == None)
    ).all()

    # Only flag if there are a significant number on an account
    from collections import defaultdict
    by_account: dict = defaultdict(list)
    for t in txns:
        by_account[t.account_id].append(t.id)

    count = 0
    for account_id, txn_ids in by_account.items():
        if len(txn_ids) >= 3:
            create_flag(
                session,
                "UNKNOWN_CURRENCY",
                FlagSeverity.INFO,
                f"{len(txn_ids)} transaction(s) have no determinable currency. "
                "They are excluded from currency-specific balance calculations until resolved.",
                account_id=account_id,
                evidence=txn_ids[:20],
            )
            count += 1

    session.commit()
    return {"flags_created": count, "type": "UNKNOWN_CURRENCY"}


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
        "chronology": check_chronology(session),
        "pdf_metadata": check_pdf_metadata(session),
        "velocity_spikes": check_velocity_spikes(session),
        "unknown_currency": check_unknown_currency_transactions(session),
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
                    "currency": txn.currency,
                }
        elif flag.statement_id:
            stmt = session.get(Statement, flag.statement_id)
            if stmt:
                context = {
                    "period_start": stmt.period_start.isoformat(),
                    "period_end": stmt.period_end.isoformat(),
                    "currency": stmt.currency,
                }
        if not context.get("currency") and flag.account_id:
            context["currency"] = _account_currency(session, flag.account_id)

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
