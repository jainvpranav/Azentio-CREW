"""Transaction endpoints"""
from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Transaction, TransactionResponse, TransactionCategory, Classification


router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("/", response_model=List[TransactionResponse])
def list_transactions(
    account_id: Optional[int] = None,
    month: Optional[str] = None,
    category: Optional[TransactionCategory] = None,
    flagged: Optional[bool] = None,
    session: Session = Depends(get_session),
):
    """
    List transactions with optional filtering.
    month format: "2026-10" (YYYY-MM)
    """
    query = select(Transaction)

    if account_id:
        query = query.where(Transaction.account_id == account_id)

    if month:
        try:
            year, month_num = month.split("-")
            # Filter transactions in this month
            from datetime import datetime
            month_start = datetime.strptime(f"{year}-{month_num}-01", "%Y-%m-%d").date()
            if month_num == "12":
                month_end = datetime.strptime(f"{int(year)+1}-01-01", "%Y-%m-%d").date()
            else:
                month_end = datetime.strptime(f"{year}-{int(month_num)+1:02d}-01", "%Y-%m-%d").date()

            query = query.where(Transaction.txn_date >= month_start)
            query = query.where(Transaction.txn_date < month_end)
        except (ValueError, IndexError):
            pass

    transactions = session.exec(query).all()

    # Get current classifications
    results = []
    for txn in transactions:
        # Get latest classification
        classification = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()

        results.append(TransactionResponse(
            id=txn.id,
            txn_date=txn.txn_date,
            description=txn.description,
            debit=txn.debit,
            credit=txn.credit,
            balance=txn.balance,
            category=classification.category if classification else None,
            rule_id=classification.rule_id if classification else None,
            reason=classification.reason if classification else None,
            page=txn.page,
            row_index=txn.row_index,
            duplicate_of=txn.duplicate_of,
        ))

    # Filter by category if specified
    if category:
        results = [r for r in results if r.category == category]

    return results


@router.get("/{txn_id}", response_model=TransactionResponse)
def get_transaction(txn_id: int, session: Session = Depends(get_session)):
    """Get transaction with full detail"""
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    classification = session.exec(
        select(Classification)
        .where(Classification.txn_id == txn.id)
        .where(Classification.is_current == True)
    ).first()

    return TransactionResponse(
        id=txn.id,
        txn_date=txn.txn_date,
        description=txn.description,
        debit=txn.debit,
        credit=txn.credit,
        balance=txn.balance,
        category=classification.category if classification else None,
        rule_id=classification.rule_id if classification else None,
        reason=classification.reason if classification else None,
        page=txn.page,
        row_index=txn.row_index,
        duplicate_of=txn.duplicate_of,
    )


@router.post("/{txn_id}/reclassify")
def reclassify_transaction(
    txn_id: int,
    category: TransactionCategory,
    note: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """Reclassify a transaction (user override)"""
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Mark old classification as not current
    old_classification = session.exec(
        select(Classification)
        .where(Classification.txn_id == txn.id)
        .where(Classification.is_current == True)
    ).first()

    if old_classification:
        old_classification.is_current = False

    # Create new classification
    new_classification = Classification(
        txn_id=txn_id,
        category=category,
        reason=note or "User reclassification",
        source="user",
        is_current=True,
        user_note=note,
    )
    session.add(new_classification)
    session.commit()
    session.refresh(new_classification)

    return {
        "txn_id": txn_id,
        "new_category": category,
        "note": note
    }
