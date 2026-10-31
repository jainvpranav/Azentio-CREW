"""
Borrower-assessment rule evaluation engine (handoff Phase 5). Evaluates the
already-computed, deterministic metrics against the configurable
thresholds in app/config/thresholds.py and produces explainable indicators
- never an automatic REJECT/DEFAULT/fraud decision (handoff instruction,
enforced by the fact that no band below is named anything stronger than
"higher_burden" / "elevated" / "possible_shortfall").

Every evaluation is written to the RuleEvaluation table (append-only,
versioned by app.config.thresholds.THRESHOLDS_VERSION) so the same inputs +
rule config reproduce the same result later (handoff "Auditability and
reproducibility").
"""
import json
from sqlmodel import Session

from app.models import RuleEvaluation, Account, EntityType, Customer
from app.config import thresholds as cfg
from app.pipeline.individual_metrics import (
    compute_vnmi, compute_namb, compute_foir, compute_discretionary_spending_ratio,
    compute_salary_to_obligation_cleansing_cycle,
)
from app.pipeline.sme_metrics import (
    compute_gbt, compute_dscr, compute_customer_concentration,
    compute_cc_od_utilization, compute_trade_inflow_outflow_ratio,
)
from app.pipeline.redflags import compute_nsf_bounce_counter, compute_round_tripping, compute_eod_balance_stress


def _record(session: Session, account_id: int, rule_id: str, metric_name: str, metric_value,
            threshold_label: str, result: str, period: str, supporting_txn_ids: list,
            confidence: str, limitations: str) -> dict:
    row = RuleEvaluation(
        rule_id=rule_id, rule_version=cfg.THRESHOLDS_VERSION, account_id=account_id,
        metric_name=metric_name, metric_value=metric_value, threshold_label=threshold_label,
        result=result, period=period or "all available months",
        supporting_txn_ids=json.dumps(supporting_txn_ids or []),
        confidence=confidence, limitations=limitations,
    )
    session.add(row)
    indicator = {
        "rule_id": rule_id, "metric_name": metric_name, "metric_value": metric_value,
        "threshold_label": threshold_label, "result": result, "period": period,
        "supporting_txn_ids": supporting_txn_ids or [], "confidence": confidence,
        "limitations": limitations, "rule_version": cfg.THRESHOLDS_VERSION,
    }
    return indicator


def _txn_ids(detail: dict, limit: int = 20) -> list:
    return [t["id"] for t in detail.get("included", [])][:limit]


def evaluate_individual(session: Session, account_id: int) -> dict:
    indicators = []

    vnmi = compute_vnmi(session, account_id)
    namb = compute_namb(session, account_id)
    foir = compute_foir(session, account_id)
    cleansing = compute_salary_to_obligation_cleansing_cycle(session, account_id)
    discretionary = compute_discretionary_spending_ratio(session, account_id)
    nsf = compute_nsf_bounce_counter(session, account_id)
    round_trip = compute_round_tripping(session, account_id)
    eod = compute_eod_balance_stress(session, account_id)

    indicators.append(_record(
        session, account_id, "Rule_Ind_FOIR", "foir", foir["value"],
        f"<={cfg.FOIR_LOWER_BURDEN_MAX} lower / <={cfg.FOIR_ELEVATED_MAX} elevated / >{cfg.FOIR_ELEVATED_MAX} higher",
        foir.get("band", "NOT_AVAILABLE"), foir.get("period"), _txn_ids(foir),
        "complete" if foir["value"] is not None else "insufficient_data",
        "; ".join(foir.get("caveats", [])),
    ))
    indicators.append(_record(
        session, account_id, "Rule_Ind_VNMI", "vnmi", vnmi["value"], "informational - not used in risk assessment",
        "computed" if vnmi["value"] is not None else "NOT_AVAILABLE", vnmi.get("period"),
        _txn_ids(vnmi), "complete" if vnmi["value"] is not None else "insufficient_data",
        "; ".join(vnmi.get("caveats", [])),
    ))
    indicators.append(_record(
        session, account_id, "Rule_Ind_NAMB", "namb", namb["value"], "informational - not used in risk assessment",
        "computed" if namb["value"] is not None else "NOT_AVAILABLE", namb.get("period"),
        _txn_ids(namb), "approximation" if namb.get("caveats") else "complete",
        "; ".join(namb.get("caveats", [])),
    ))
    indicators.append(_record(
        session, account_id, "Rule_Ind_DiscretionaryRatio", "discretionary_spending_ratio",
        discretionary["value"], "informational - not used in risk assessment",
        "computed" if discretionary["value"] is not None else "NOT_AVAILABLE", discretionary.get("period"),
        _txn_ids(discretionary), "complete", "; ".join(discretionary.get("caveats", [])),
    ))
    indicators.append(_record(
        session, account_id, "Rule_Ind_NSF", "nsf_bounce_count", nsf["total_count"],
        "any occurrence is reviewable", "flagged" if nsf["total_count"] > 0 else "clear",
        "all available months", [tid for e in nsf["events"] for tid in e["txn_ids"]],
        "complete", "Keyword-based detection; a non-matching return code would not be counted.",
    ))
    indicators.append(_record(
        session, account_id, "Rule_Ind_RoundTrip", "round_tripping_count", round_trip["total_count"],
        "any occurrence is reviewable", "flagged" if round_trip["total_count"] > 0 else "clear",
        "all available months", [m["out_txn_id"] for m in round_trip["matches"]],
        "complete", "Pattern match only - never a money-laundering determination.",
    ))
    indicators.append(_record(
        session, account_id, "Rule_Ind_EODStress", "eod_consecutive_stress_days",
        eod["longest_consecutive_stress_days"],
        f">={cfg.EOD_STRESS_CONSECUTIVE_DAYS_WARN} days is reviewable",
        "flagged" if eod["longest_consecutive_stress_days"] >= cfg.EOD_STRESS_CONSECUTIVE_DAYS_WARN else "clear",
        "all available months", [], "complete",
        "A low balance alone does not by itself indicate financial distress.",
    ))

    session.commit()

    elevated_count = sum(1 for i in indicators if i["result"] in ("elevated", "higher_burden", "flagged"))
    review_priority = "higher_review_priority" if elevated_count >= 3 else ("elevated" if elevated_count >= 1 else "lower_review_priority")

    return {
        "account_id": account_id,
        "entity_type": "INDIVIDUAL",
        "indicators": indicators,
        "review_priority": review_priority,
        "review_priority_note": (
            f"{elevated_count} indicator(s) outside the configured band, out of {len(indicators)} evaluated. "
            "This is an aggregation of explainable indicators for human review, not an automated approve/reject decision."
        ),
        "detail": {
            "vnmi": vnmi, "namb": namb, "foir": foir, "cleansing_cycle": cleansing,
            "discretionary_spending_ratio": discretionary, "nsf_bounce_counter": nsf,
            "round_tripping": round_trip, "eod_balance_stress": eod,
        },
    }


def evaluate_sme(session: Session, account_id: int) -> dict:
    indicators = []

    gbt = compute_gbt(session, account_id)
    dscr = compute_dscr(session, account_id)
    concentration = compute_customer_concentration(session, account_id)
    cc_od = compute_cc_od_utilization(session, account_id)
    trade_ratio = compute_trade_inflow_outflow_ratio(session, account_id)
    nsf = compute_nsf_bounce_counter(session, account_id)
    round_trip = compute_round_tripping(session, account_id)
    eod = compute_eod_balance_stress(session, account_id)

    indicators.append(_record(
        session, account_id, "Rule_SME_GBT", "gbt", gbt["value"], "n/a (informational)",
        "computed", gbt.get("period"), _txn_ids(gbt), "complete", "; ".join(gbt.get("caveats", [])),
    ))
    dscr_value = dscr["value"] if isinstance(dscr["value"], (int, float)) else None
    indicators.append(_record(
        session, account_id, "Rule_SME_DSCR", "dscr", dscr_value,
        f"<{cfg.DSCR_SHORTFALL_MAX} possible shortfall / >={cfg.DSCR_STRONG_MIN} strong coverage",
        dscr.get("band", "NOT_AVAILABLE"), dscr.get("period"), _txn_ids(dscr),
        "complete" if dscr_value is not None else "insufficient_data", "; ".join(dscr.get("caveats", [])),
    ))
    top1 = concentration.get("top1_share")
    indicators.append(_record(
        session, account_id, "Rule_SME_Concentration", "customer_concentration_top1", top1,
        f">{cfg.CONCENTRATION_TOP1_ELEVATED_MIN}% elevated",
        "elevated" if concentration.get("top1_elevated") else ("computed" if top1 is not None else "NOT_AVAILABLE"),
        "all available months", _txn_ids(concentration), "complete", "; ".join(concentration.get("caveats", [])),
    ))
    cc_value = cc_od["value"] if isinstance(cc_od["value"], (int, float)) else None
    indicators.append(_record(
        session, account_id, "Rule_SME_CCOD", "cc_od_utilization", cc_value,
        f">{cfg.CC_OD_UTILIZATION_PRESSURE_MIN}% may indicate liquidity pressure",
        "liquidity_pressure" if cc_od.get("liquidity_pressure") else cc_od["value"] if cc_value is None else "computed",
        "all available months", [], "complete" if cc_value is not None else "missing_metadata",
        "; ".join(cc_od.get("caveats", [])),
    ))
    trade_value = trade_ratio["value"] if isinstance(trade_ratio["value"], (int, float)) else None
    indicators.append(_record(
        session, account_id, "Rule_SME_TradeRatio", "trade_inflow_outflow_ratio", trade_value,
        "n/a (informational)", "computed" if trade_value is not None else "NOT_AVAILABLE",
        "all available months", _txn_ids(trade_ratio), "complete" if trade_value is not None else "insufficient_data",
        "; ".join(trade_ratio.get("caveats", [])),
    ))
    indicators.append(_record(
        session, account_id, "Rule_SME_NSF", "nsf_bounce_count", nsf["total_count"],
        "any occurrence is reviewable", "flagged" if nsf["total_count"] > 0 else "clear",
        "all available months", [tid for e in nsf["events"] for tid in e["txn_ids"]],
        "complete", "Keyword-based detection.",
    ))
    indicators.append(_record(
        session, account_id, "Rule_SME_RoundTrip", "round_tripping_count", round_trip["total_count"],
        "any occurrence is reviewable", "flagged" if round_trip["total_count"] > 0 else "clear",
        "all available months", [m["out_txn_id"] for m in round_trip["matches"]],
        "complete", "Pattern match only - never a money-laundering determination.",
    ))
    indicators.append(_record(
        session, account_id, "Rule_SME_EODStress", "eod_consecutive_stress_days",
        eod["longest_consecutive_stress_days"],
        f">={cfg.EOD_STRESS_CONSECUTIVE_DAYS_WARN} days is reviewable",
        "flagged" if eod["longest_consecutive_stress_days"] >= cfg.EOD_STRESS_CONSECUTIVE_DAYS_WARN else "clear",
        "all available months", [], "complete",
        "A low balance alone does not by itself indicate financial distress.",
    ))

    session.commit()

    elevated_terms = ("elevated", "possible_shortfall", "liquidity_pressure", "flagged")
    elevated_count = sum(1 for i in indicators if i["result"] in elevated_terms)
    review_priority = "higher_review_priority" if elevated_count >= 3 else ("elevated" if elevated_count >= 1 else "lower_review_priority")

    return {
        "account_id": account_id,
        "entity_type": "SME",
        "indicators": indicators,
        "review_priority": review_priority,
        "review_priority_note": (
            f"{elevated_count} indicator(s) outside the configured band, out of {len(indicators)} evaluated. "
            "This is an aggregation of explainable indicators for human review, not an automated approve/reject decision."
        ),
        "detail": {
            "gbt": gbt, "dscr": dscr, "customer_concentration": concentration,
            "cc_od_utilization": cc_od, "trade_inflow_outflow_ratio": trade_ratio,
            "nsf_bounce_counter": nsf, "round_tripping": round_trip, "eod_balance_stress": eod,
        },
    }


def resolve_entity_type(session: Session, account_id: int) -> EntityType:
    """
    A-001: entity type is selected (via Customer.entity_type), not inferred.
    Defaults to INDIVIDUAL when the account has no linked customer.
    """
    account = session.get(Account, account_id)
    if account and account.customer_id:
        customer = session.get(Customer, account.customer_id)
        if customer:
            return customer.entity_type
    return EntityType.INDIVIDUAL


def evaluate_account(session: Session, account_id: int) -> dict:
    entity_type = resolve_entity_type(session, account_id)
    if entity_type == EntityType.SME:
        return evaluate_sme(session, account_id)
    return evaluate_individual(session, account_id)
