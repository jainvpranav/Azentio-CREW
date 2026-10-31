"""Metrics, classification, and flags endpoints"""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.pipeline.classify import classify_all_transactions
from app.pipeline.metrics import get_all_metrics, compute_income
from app.pipeline.flags import generate_all_flags, get_flag_queue


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.post("/classify-all")
def classify_all(session: Session = Depends(get_session)):
    """Classify all unclassified transactions using rules"""
    return classify_all_transactions(session)


@router.get("/account/{account_id}")
def get_metrics(account_id: int, session: Session = Depends(get_session)):
    """Get all metrics for an account"""
    return get_all_metrics(session, account_id)


@router.get("/account/{account_id}/income")
def get_income(account_id: int, session: Session = Depends(get_session)):
    """Get estimated income for an account"""
    return compute_income(session, account_id)


@router.post("/flags/generate")
def generate_flags(session: Session = Depends(get_session)):
    """Generate all data quality flags"""
    return generate_all_flags(session)


@router.get("/flags")
def get_flags(session: Session = Depends(get_session)):
    """Get all flags"""
    return get_flag_queue(session)
