"""Metrics, classification, and flags endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.pipeline.classify import classify_all_transactions
from app.pipeline.metrics import (
    get_all_metrics,
    compute_income,
    get_metrics_summary,
    compute_metric_detail,
    compute_balance_trend,
    METRIC_NAMES,
)
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


@router.get("/account/{account_id}/summary")
def get_metrics_summary_route(account_id: int, session: Session = Depends(get_session)):
    """Headline metric cards + monthly series, for the Analysis dashboard."""
    return get_metrics_summary(session, account_id)


@router.get("/account/{account_id}/balance-trend")
def get_balance_trend(account_id: int, session: Session = Depends(get_session)):
    """Month-end balance, min balance, days below threshold."""
    return compute_balance_trend(session, account_id)


@router.get("/account/{account_id}/detail/{metric_name}")
def get_metric_detail_route(account_id: int, metric_name: str, session: Session = Depends(get_session)):
    """Full MetricResult breakdown (included/excluded/caveats) for one metric, for the drill-down drawer."""
    if metric_name not in METRIC_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown metric '{metric_name}'. Valid: {METRIC_NAMES}")
    return compute_metric_detail(session, account_id, metric_name)


@router.post("/flags/generate")
def generate_flags(session: Session = Depends(get_session)):
    """Generate all data quality flags"""
    return generate_all_flags(session)


@router.get("/flags")
def get_flags(session: Session = Depends(get_session)):
    """Get all flags"""
    return get_flag_queue(session)
