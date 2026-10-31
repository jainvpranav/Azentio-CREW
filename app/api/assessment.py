"""
Borrower assessment, red-flag, anomaly, AI Reviewer and report endpoints
(handoff Phases 3-7). Kept in their own router, separate from the existing
metrics/flags endpoints in app/api/metrics.py, since they operate at the
account/case level rather than the single-metric level.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Customer, EntityType, Facility, AIReview, HumanDecision
from app.pipeline.rules_engine import evaluate_account, evaluate_individual, evaluate_sme
from app.pipeline import anomalies as anomalies_pipeline
from app.pipeline.redflags import generate_red_flags, generate_red_flags_all
from app.pipeline.reports import build_individual_report, build_sme_report
from app.ai.reviewer import review_pending_flags


router = APIRouter(prefix="/api/assessment", tags=["assessment"])


# ===================== Customer / entity type (ASSUMPTIONS A-001) =====================

class CustomerCreate(BaseModel):
    name: str
    entity_type: EntityType = EntityType.INDIVIDUAL


@router.post("/customers")
def create_customer(body: CustomerCreate, session: Session = Depends(get_session)):
    customer = Customer(name=body.name, entity_type=body.entity_type)
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


@router.get("/customers")
def list_customers(session: Session = Depends(get_session)):
    return session.exec(select(Customer)).all()


@router.post("/accounts/{account_id}/link-customer/{customer_id}")
def link_account_to_customer(account_id: int, customer_id: int, session: Session = Depends(get_session)):
    from app.models import Account

    account = session.get(Account, account_id)
    customer = session.get(Customer, customer_id)
    if not account or not customer:
        raise HTTPException(status_code=404, detail="Account or customer not found")
    account.customer_id = customer_id
    session.add(account)
    session.commit()
    return {"account_id": account_id, "customer_id": customer_id, "entity_type": customer.entity_type}


# ===================== Facility metadata (ASSUMPTIONS A-003) =====================

class FacilityCreate(BaseModel):
    account_id: int
    facility_type: str  # "CC" or "OD"
    sanctioned_limit: Optional[float] = None
    source_note: Optional[str] = None


@router.post("/facilities")
def create_facility(body: FacilityCreate, session: Session = Depends(get_session)):
    if body.facility_type not in ("CC", "OD"):
        raise HTTPException(status_code=400, detail="facility_type must be 'CC' or 'OD'")
    facility = Facility(
        account_id=body.account_id, facility_type=body.facility_type,
        sanctioned_limit=body.sanctioned_limit, source_note=body.source_note,
    )
    session.add(facility)
    session.commit()
    session.refresh(facility)
    return facility


# ===================== Anomalies & red flags (Phases 1, 3) =====================

@router.post("/account/{account_id}/anomalies/run")
def run_anomalies(account_id: int, session: Session = Depends(get_session)):
    """Category-specific anomaly detection (handoff Phase 1's per-category anomaly lists)."""
    return anomalies_pipeline.run_all(session, account_id)


@router.post("/account/{account_id}/redflags/run")
def run_redflags(account_id: int, session: Session = Depends(get_session)):
    """NSF/Bounce, round-tripping, EOD balance stress (handoff Phase 3)."""
    return generate_red_flags(session, account_id)


@router.post("/redflags/run-all")
def run_redflags_all(session: Session = Depends(get_session)):
    return generate_red_flags_all(session)


# ===================== Borrower assessment / rule engine (Phase 5) =====================

@router.get("/account/{account_id}")
def get_assessment(account_id: int, entity_type: Optional[EntityType] = None, session: Session = Depends(get_session)):
    """
    Evaluates the configured rules for this account and returns explainable
    indicators + a review-priority aggregation (never an approve/reject
    decision). `entity_type` overrides the stored Customer.entity_type for
    this call only, for exploring "what would this look like as SME".
    """
    if entity_type == EntityType.SME:
        return evaluate_sme(session, account_id)
    if entity_type == EntityType.INDIVIDUAL:
        return evaluate_individual(session, account_id)
    return evaluate_account(session, account_id)


# ===================== AI Reviewer (Phase 6) =====================

@router.post("/account/{account_id}/ai-review/run")
def run_ai_review(account_id: int, limit: int = 50, session: Session = Depends(get_session)):
    """
    Runs the AI Reviewer for this account's pending (not-yet-reviewed)
    flags. Falls back to a deterministic NEEDS_INFORMATION result per case
    if no LLM provider is configured (ASSUMPTIONS.md A-005) - never fails
    the request and never fabricates a review.
    """
    reviews = review_pending_flags(session, account_id=account_id, limit=limit)
    return {
        "reviewed_count": len(reviews),
        "llm_configured": any(r.llm_model_name for r in reviews),
        "reviews": [
            {
                "id": r.id, "case_id": r.case_id, "recommendation": r.recommendation,
                "confidence": r.confidence, "human_decision": r.human_decision,
            }
            for r in reviews
        ],
    }


@router.get("/account/{account_id}/ai-review")
def get_ai_reviews(account_id: int, session: Session = Depends(get_session)):
    return session.exec(select(AIReview).where(AIReview.account_id == account_id)).all()


class HumanDecisionBody(BaseModel):
    decision: HumanDecision
    note: Optional[str] = None


@router.post("/ai-review/{review_id}/decide")
def record_human_decision(review_id: int, body: HumanDecisionBody, session: Session = Depends(get_session)):
    """
    Records the human reviewer's final call on an AI-reviewed case.
    NEEDS_INFORMATION and ESCALATE_TO_HUMAN cases, and any case tied to a
    HIGH-severity flag, always land here pending a human click - this
    endpoint is that click (handoff: "Do not remove human review for cases
    that policy requires a person to decide").
    """
    review = session.get(AIReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="AI review not found")
    review.human_decision = body.decision
    review.human_decision_note = body.note
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


# ===================== Reports (Phase 7) =====================

@router.get("/account/{account_id}/report")
def get_report(account_id: int, entity_type: Optional[EntityType] = None, session: Session = Depends(get_session)):
    from app.pipeline.rules_engine import resolve_entity_type

    resolved = entity_type or resolve_entity_type(session, account_id)
    if resolved == EntityType.SME:
        return build_sme_report(session, account_id)
    return build_individual_report(session, account_id)
