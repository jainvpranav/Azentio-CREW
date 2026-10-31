"""Transaction endpoints"""
from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from sqlalchemy import func
from app.db import get_session
from app.models import Transaction, TransactionResponse, TransactionCategory, Classification


class ReclassifyRequest(BaseModel):
    category: TransactionCategory
    note: Optional[str] = None


router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("/count")
def count_transactions(session: Session = Depends(get_session)):
    """Lightweight count endpoint — avoids loading full transaction list."""
    total = session.exec(select(func.count()).select_from(Transaction)).one()
    duplicates = session.exec(
        select(func.count()).select_from(Transaction).where(Transaction.duplicate_of != None)
    ).one()
    return {"total": total, "duplicates": duplicates}


@router.get("/audit/corrections")
def get_corrections(session: Session = Depends(get_session)):
    """
    Classification audit trail: every transaction with more than one
    Classification row (i.e. corrected at least once), original and current
    both visible (append-only per BUILD_PLAN principle #4).
    """
    all_classifications = session.exec(
        select(Classification).order_by(Classification.txn_id, Classification.created_at)
    ).all()

    by_txn: dict = {}
    for c in all_classifications:
        by_txn.setdefault(c.txn_id, []).append(c)

    corrections = []
    for txn_id, history in by_txn.items():
        if len(history) < 2:
            continue
        txn = session.get(Transaction, txn_id)
        corrections.append({
            "txn_id": txn_id,
            "description": txn.description if txn else None,
            "txn_date": txn.txn_date.isoformat() if txn else None,
            "history": [
                {
                    "category": c.category,
                    "rule_id": c.rule_id,
                    "reason": c.reason,
                    "source": c.source,
                    "is_current": c.is_current,
                    "user_note": c.user_note,
                    "created_at": c.created_at.isoformat(),
                }
                for c in history
            ],
        })

    corrections.sort(key=lambda c: c["history"][-1]["created_at"], reverse=True)
    return {"total": len(corrections), "corrections": corrections}


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
            subcategory=classification.subcategory if classification else None,
            classification_confidence=classification.confidence if classification else None,
            rule_id=classification.rule_id if classification else None,
            reason=classification.reason if classification else None,
            page=txn.page,
            row_index=txn.row_index,
            duplicate_of=txn.duplicate_of,
            counterparty=txn.counterparty,
            counterparty_account=txn.counterparty_account,
            reference_number=txn.reference_number,
            transaction_type=txn.transaction_type,
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
        subcategory=classification.subcategory if classification else None,
        classification_confidence=classification.confidence if classification else None,
        rule_id=classification.rule_id if classification else None,
        reason=classification.reason if classification else None,
        page=txn.page,
        row_index=txn.row_index,
        duplicate_of=txn.duplicate_of,
        counterparty=txn.counterparty,
        counterparty_account=txn.counterparty_account,
        reference_number=txn.reference_number,
        transaction_type=txn.transaction_type,
    )


@router.post("/{txn_id}/reclassify")
def reclassify_transaction(
    txn_id: int,
    body: ReclassifyRequest,
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
        session.add(old_classification)

    # Create new classification
    new_classification = Classification(
        txn_id=txn_id,
        category=body.category,
        reason=body.note or "User reclassification",
        source="user",
        is_current=True,
        user_note=body.note,
    )
    session.add(new_classification)
    session.commit()
    session.refresh(new_classification)

    return {
        "txn_id": txn_id,
        "new_category": body.category,
        "note": body.note
    }
