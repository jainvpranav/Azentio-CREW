"""Coverage analysis - which months are covered"""
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from sqlmodel import Session, select

from app.models import Account, Statement, Transaction


def get_month_coverage(session: Session, account_id: int) -> dict:
    """
    Get month-by-month coverage for an account.

    Returns:
        {
            "account_id": int,
            "coverage_grid": {
                "2026-10": "full",   # full | partial | missing
                "2026-11": "missing"
            },
            "months_full": int,
            "months_partial": int,
            "months_missing": int,
        }
    """
    statements = session.exec(
        select(Statement)
        .where(Statement.account_id == account_id)
    ).all()

    if not statements:
        return {
            "account_id": account_id,
            "coverage_grid": {},
            "months_full": 0,
            "months_partial": 0,
            "months_missing": 0,
        }

    # Find min/max month
    min_date = min(s.period_start for s in statements)
    max_date = max(s.period_end for s in statements)

    coverage_grid = {}
    current_month = date(min_date.year, min_date.month, 1)
    end_month = date(max_date.year, max_date.month, 1)

    months_full = 0
    months_partial = 0
    months_missing = 0

    while current_month <= end_month:
        month_key = current_month.strftime("%Y-%m")

        # Check if any statement covers this month
        month_start = current_month
        month_end = (current_month + relativedelta(months=1)) - relativedelta(days=1)

        covering_statements = [
            s for s in statements
            if s.period_start <= month_end and s.period_end >= month_start
        ]

        if not covering_statements:
            status = "missing"
            months_missing += 1
        else:
            # Check if full coverage (at least one statement fully covers the month)
            full_coverage = any(
                s.period_start <= month_start and s.period_end >= month_end
                for s in covering_statements
            )
            status = "full" if full_coverage else "partial"
            if status == "full":
                months_full += 1
            else:
                months_partial += 1

        coverage_grid[month_key] = status
        current_month += relativedelta(months=1)

    return {
        "account_id": account_id,
        "coverage_grid": coverage_grid,
        "months_full": months_full,
        "months_partial": months_partial,
        "months_missing": months_missing,
    }


def get_all_coverage(session: Session) -> dict:
    """Get coverage for all accounts"""
    accounts = session.exec(select(Account)).all()

    return {
        "accounts": [
            get_month_coverage(session, account.id)
            for account in accounts
        ]
    }
