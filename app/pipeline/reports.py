"""
Individual and SME reports (handoff Phase 7). Assembles already-computed
metrics/indicators/flags/AI-review rows into the two report shapes the
handoff asks for. Does not compute anything new itself - every number here
traces back to app/pipeline/{individual_metrics,sme_metrics,redflags,
rules_engine,anomalies}.py and app/ai/reviewer.py, so the drill-down from a
report number to its supporting transactions is the same drill-down the
Analysis dashboard already provides.
"""
from collections import defaultdict
from sqlmodel import Session, select

from app.models import Flag, AIReview, Account
from app.pipeline.metrics import compute_metric_detail
from app.pipeline.rules_engine import evaluate_individual, evaluate_sme
from app.pipeline import anomalies as anomalies_pipeline


def _grouped_flags(session: Session, account_id: int) -> dict:
    """Group flags by type to reduce alert fatigue (handoff Phase 7 instruction)."""
    flags = session.exec(select(Flag).where(Flag.account_id == account_id)).all()
    grouped = defaultdict(list)
    for f in flags:
        grouped[f.flag_type].append({
            "id": f.id, "severity": f.severity.value, "message": f.message,
            "txn_id": f.txn_id, "statement_id": f.statement_id,
            "created_at": f.created_at.isoformat(),
        })
    return {
        flag_type: {"count": len(items), "severity": items[0]["severity"], "items": items}
        for flag_type, items in grouped.items()
    }


def _ai_review_findings(session: Session, account_id: int) -> list:
    reviews = session.exec(select(AIReview).where(AIReview.account_id == account_id)).all()
    return [
        {
            "case_id": r.case_id, "triggered_rule": r.triggered_rule,
            "recommendation": r.recommendation.value, "confidence": r.confidence,
            "observed_facts": r.observed_facts, "possible_explanations": r.possible_explanations,
            "unresolved_questions": r.unresolved_questions, "escalation_reason": r.escalation_reason,
            "human_decision": r.human_decision.value, "llm_model_name": r.llm_model_name,
            "created_at": r.created_at.isoformat(),
        }
        for r in reviews
    ]


def build_individual_report(session: Session, account_id: int) -> dict:
    account = session.get(Account, account_id)
    assessment = evaluate_individual(session, account_id)
    anomaly_detail = anomalies_pipeline.run_all(session, account_id)

    monthly_income = compute_metric_detail(session, account_id, "monthly_credits_adjusted")
    monthly_expense = compute_metric_detail(session, account_id, "monthly_debits_adjusted")
    recurring = compute_metric_detail(session, account_id, "recurring_obligations")

    return {
        "report_type": "INDIVIDUAL",
        "account": {"id": account_id, "holder_name": account.holder_name if account else None,
                     "account_number": account.account_number if account else None},
        "metrics": {
            "vnmi": assessment["detail"]["vnmi"],
            "namb": assessment["detail"]["namb"],
            "foir": assessment["detail"]["foir"],
            "salary_to_obligation_cleansing_cycle": assessment["detail"]["cleansing_cycle"],
            "discretionary_spending_ratio": assessment["detail"]["discretionary_spending_ratio"],
        },
        "monthly_trends": {
            "income_by_month": monthly_income["by_month"],
            "expense_by_month": monthly_expense["by_month"],
        },
        "emi_and_spending_breakdown": recurring,
        "red_flags": _grouped_flags(session, account_id),
        "category_anomalies": anomaly_detail,
        "ai_reviewer_findings": _ai_review_findings(session, account_id),
        "review_priority": assessment["review_priority"],
        "review_priority_note": assessment["review_priority_note"],
        "indicators": assessment["indicators"],
        "disclaimer": (
            "This report presents explainable indicators for analyst review. It is not a credit "
            "approval/rejection decision and does not assert fraud or default."
        ),
    }


def build_sme_report(session: Session, account_id: int) -> dict:
    account = session.get(Account, account_id)
    assessment = evaluate_sme(session, account_id)
    anomaly_detail = anomalies_pipeline.run_all(session, account_id)

    monthly_inflow = compute_metric_detail(session, account_id, "monthly_credits_adjusted")
    monthly_outflow = compute_metric_detail(session, account_id, "monthly_debits_adjusted")

    return {
        "report_type": "SME",
        "account": {"id": account_id, "holder_name": account.holder_name if account else None,
                     "account_number": account.account_number if account else None},
        "metrics": {
            "gbt": assessment["detail"]["gbt"],
            "dscr": assessment["detail"]["dscr"],
            "customer_concentration": assessment["detail"]["customer_concentration"],
            "cc_od_utilization": assessment["detail"]["cc_od_utilization"],
            "trade_inflow_outflow_ratio": assessment["detail"]["trade_inflow_outflow_ratio"],
        },
        "monthly_trends": {
            "business_inflow_by_month": monthly_inflow["by_month"],
            "business_outflow_by_month": monthly_outflow["by_month"],
        },
        "customer_receipts": assessment["detail"]["customer_concentration"].get("ranked_customers", []),
        "liquidity_working_capital": {
            "namb_not_applicable_for_sme_report": "See eod_balance_stress below for liquidity signal.",
            "eod_balance_stress": assessment["detail"]["eod_balance_stress"],
        },
        "red_flags": _grouped_flags(session, account_id),
        "category_anomalies": anomaly_detail,
        "ai_reviewer_findings": _ai_review_findings(session, account_id),
        "review_priority": assessment["review_priority"],
        "review_priority_note": assessment["review_priority_note"],
        "indicators": assessment["indicators"],
        "disclaimer": (
            "This report presents explainable indicators for analyst review. It is not a credit "
            "approval/rejection decision and does not assert fraud or default."
        ),
    }
