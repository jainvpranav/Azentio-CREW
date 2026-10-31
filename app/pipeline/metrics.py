"""Compute financial metrics from transactions"""
from decimal import Decimal
from datetime import date
from collections import defaultdict
from sqlmodel import Session, select

from app.models import Transaction, Classification, TransactionCategory, Account


def compute_monthly_credits(session: Session, account_id: int) -> dict:
    """Compute total credits by month"""
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.credit != None)
    ).all()

    monthly = defaultdict(Decimal)
    for txn in transactions:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key] += txn.credit

    return {
        "metric": "monthly_credits",
        "account_id": account_id,
        "by_month": {k: float(v) for k, v in sorted(monthly.items())},
    }


def compute_monthly_debits(session: Session, account_id: int) -> dict:
    """Compute total debits by month"""
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.debit != None)
    ).all()

    monthly = defaultdict(Decimal)
    for txn in transactions:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key] += txn.debit

    return {
        "metric": "monthly_debits",
        "account_id": account_id,
        "by_month": {k: float(v) for k, v in sorted(monthly.items())},
    }


def compute_income(session: Session, account_id: int) -> dict:
    """
    Estimate income from SALARY and BUSINESS_RECEIPT transactions.
    Returns median monthly income if salaried.
    """
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.credit != None)
    ).all()

    monthly_income = defaultdict(Decimal)

    for txn in transactions:
        # Get current classification
        classification = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        if not classification:
            continue

        # Count only salary and business receipts
        if classification.category in [TransactionCategory.SALARY, TransactionCategory.BUSINESS_RECEIPT]:
            month_key = txn.txn_date.strftime("%Y-%m")
            monthly_income[month_key] += txn.credit

    if not monthly_income:
        return {
            "metric": "estimated_income",
            "account_id": account_id,
            "value": None,
            "by_month": {},
            "status": "no_income_found"
        }

    values = sorted(monthly_income.values())
    median = values[len(values) // 2] if values else Decimal(0)

    return {
        "metric": "estimated_income",
        "account_id": account_id,
        "value": float(median),
        "by_month": {k: float(v) for k, v in sorted(monthly_income.items())},
        "status": "calculated"
    }


def compute_recurring_obligations(session: Session, account_id: int) -> dict:
    """
    Find recurring debits: EMI, RENT, UTILITIES, etc.
    Returns sum of identified recurring debits per month.
    """
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.debit != None)
    ).all()

    recurring_debit = Decimal(0)

    for txn in transactions:
        classification = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        if not classification:
            continue

        # Count recurring categories
        if classification.category in [
            TransactionCategory.LOAN_EMI,
            TransactionCategory.RENT,
            TransactionCategory.UTILITIES,
            TransactionCategory.CARD_PAYMENT
        ]:
            recurring_debit += txn.debit

    # Rough estimate: divide by number of months
    months = len(set(t.txn_date.strftime("%Y-%m") for t in transactions))
    monthly_recurring = recurring_debit / months if months > 0 else Decimal(0)

    return {
        "metric": "recurring_obligations",
        "account_id": account_id,
        "estimated_monthly": float(monthly_recurring),
        "total_identified": float(recurring_debit),
    }


def compute_net_cashflow(session: Session, account_id: int) -> dict:
    """Net credits - debits by month"""
    credits = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.credit != None)
    ).all()

    debits = session.exec(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.debit != None)
    ).all()

    monthly = defaultdict(lambda: [Decimal(0), Decimal(0)])  # [credits, debits]

    for txn in credits:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key][0] += txn.credit

    for txn in debits:
        month_key = txn.txn_date.strftime("%Y-%m")
        monthly[month_key][1] += txn.debit

    cashflow = {k: float(monthly[k][0] - monthly[k][1]) for k in monthly}

    return {
        "metric": "net_cashflow",
        "account_id": account_id,
        "by_month": dict(sorted(cashflow.items())),
    }


def get_all_metrics(session: Session, account_id: int) -> dict:
    """Compute all metrics for an account"""
    return {
        "account_id": account_id,
        "monthly_credits": compute_monthly_credits(session, account_id),
        "monthly_debits": compute_monthly_debits(session, account_id),
        "income": compute_income(session, account_id),
        "recurring_obligations": compute_recurring_obligations(session, account_id),
        "net_cashflow": compute_net_cashflow(session, account_id),
    }
