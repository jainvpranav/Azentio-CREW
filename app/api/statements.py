"""Statement and preprocessing endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import StatementResponse
from app.pipeline.reconcile import reconcile_statement
from app.pipeline.dedupe import deduplicate_account, deduplicate_all
from app.pipeline.coverage import get_month_coverage, get_all_coverage


router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.get("/{statement_id}", response_model=StatementResponse)
def get_statement(statement_id: int, session: Session = Depends(get_session)):
    """Get statement details"""
    from app.models import Statement
    statement = session.get(Statement, statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Statement not found")

    return StatementResponse(
        id=statement.id,
        account_id=statement.account_id,
        period_start=statement.period_start,
        period_end=statement.period_end,
        opening_balance=statement.opening_balance,
        closing_balance=statement.closing_balance,
        computed_closing=statement.computed_closing,
        reconciled=statement.reconciled,
        discrepancy=statement.discrepancy,
    )


@router.post("/{statement_id}/reconcile")
def reconcile(statement_id: int, session: Session = Depends(get_session)):
    """Reconcile a statement (opening + txns = closing)"""
    return reconcile_statement(session, statement_id)


@router.post("/account/{account_id}/dedupe")
def dedupe_account(account_id: int, session: Session = Depends(get_session)):
    """Deduplicate transactions in an account"""
    return deduplicate_account(session, account_id)


@router.post("/dedupe-all")
def dedupe_all(session: Session = Depends(get_session)):
    """Deduplicate all accounts"""
    return deduplicate_all(session)


@router.post("/process-all")
def process_all_documents(session: Session = Depends(get_session)):
    """
    Run the full post-upload pipeline (handoff: "Normalized transactions ->
    Classification -> Metric calculation -> Deterministic anomaly detection
    -> AI Reviewer -> Human review"; the AI Reviewer step is intentionally
    NOT run here - see app/api/assessment.py:run_ai_review - since it may
    call a paid external API and should be triggered explicitly):
    1. Deduplicate all accounts
    2. Reconcile all statements
    3. Get coverage for all accounts
    4. Classify all transactions (rules + pairing)
    5. Generate data-quality review flags
    6. Category-specific anomaly detection (Phase 1 anomaly lists)
    7. Red-flag metrics: NSF/bounce, round-tripping, EOD balance stress (Phase 3)
    """
    from app.models import Statement, Account
    from sqlmodel import select
    from app.pipeline.classify import classify_all_transactions
    from app.pipeline.flags import generate_all_flags
    from app.pipeline import anomalies as anomalies_pipeline
    from app.pipeline.redflags import generate_red_flags_all

    # 1. Deduplicate
    dedupe_result = deduplicate_all(session)

    # 2. Reconcile all statements
    statements = session.exec(select(Statement)).all()
    reconcile_results = []
    for statement in statements:
        result = reconcile_statement(session, statement.id)
        reconcile_results.append(result)

    # 3. Get coverage
    coverage_result = get_all_coverage(session)

    # 4. Classify (depends on dedupe having run, for duplicate exclusion downstream)
    classify_result = classify_all_transactions(session)

    # 5. Flags (depends on reconcile + classify having run)
    flags_result = generate_all_flags(session)

    # 6-7. Category anomalies + red-flag metrics (depend on classify having run)
    accounts = session.exec(select(Account)).all()
    anomalies_result = {a.id: anomalies_pipeline.run_all(session, a.id) for a in accounts}
    redflags_result = generate_red_flags_all(session)

    return {
        "dedupe": dedupe_result,
        "reconcile": {
            "statements_reconciled": len(reconcile_results),
            "results": reconcile_results,
        },
        "coverage": coverage_result,
        "classify": classify_result,
        "flags": flags_result,
        "anomalies_by_account": anomalies_result,
        "redflags_by_account": redflags_result,
    }


@router.get("/account/{account_id}/coverage")
def get_coverage(account_id: int, session: Session = Depends(get_session)):
    """Get month coverage for an account"""
    return get_month_coverage(session, account_id)
