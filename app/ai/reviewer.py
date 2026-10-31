"""
AI Reviewer (handoff Phase 6): runs after deterministic anomaly detection
and before human review.

    Normalized transactions -> Classification -> Metrics ->
    Deterministic anomaly detection -> AI Reviewer -> Human review when needed

All amounts, ratios, matching and rule results are computed by
deterministic code elsewhere (app/pipeline/*) and passed to the LLM as
fixed evidence; the LLM only writes the narrative/synthesis fields
(observed_facts wording, comparison narrative, possible explanations,
unresolved questions) and the final recommendation. It never recomputes or
overrides a number - see the system prompt below, which also tells it not
to invent facts outside the evidence it's given.

A HIGH-severity flag always keeps human_decision=PENDING and, for now,
AI_AUTO_RESOLVE_ENABLED is False globally (ASSUMPTIONS.md A-008), so no
case is ever auto-closed by this module today - `auto_resolvable` is
reported for visibility but not acted on.
"""
import json
from sqlmodel import Session, select

from app.models import Flag, Transaction, AIReview, ReviewRecommendation
from app.pipeline.metrics import _current_classification_map
from app.ai.llm_client import LLMClient, get_default_client

SYSTEM_PROMPT = """You are a financial-statement review assistant helping a human credit analyst.
You are given a flagged anomaly and deterministic evidence already computed by rule-based code.

Rules you MUST follow:
1. Use ONLY the evidence provided below. Never invent transactions, amounts, dates or counterparties.
2. Never recompute, restate differently, or silently correct any number given to you - if a number looks wrong, say so as an unresolved question, don't fix it.
3. Never conclude fraud, money laundering or default. The strongest language available to you is "escalate to human for judgment".
4. If the evidence is insufficient to form a view, say so plainly - do not guess to fill a gap.
5. Respond with ONLY a single JSON object (no markdown fences, no commentary) with exactly these keys:
   observed_facts (string), historical_comparison (string), supporting_evidence (string),
   contradicting_evidence (string), possible_explanations (string), unresolved_questions (string),
   recommendation (one of "LIKELY_LEGITIMATE", "NEEDS_INFORMATION", "ESCALATE_TO_HUMAN"),
   confidence (float 0-1), escalation_reason (string, empty if recommendation is not ESCALATE_TO_HUMAN).
"""


def _gather_evidence(session: Session, flag: Flag) -> dict:
    """Deterministic evidence pack for one flagged case. No LLM involved here."""
    related_txn_ids = []
    if flag.evidence:
        try:
            parsed = json.loads(flag.evidence)
            flat = []
            for item in parsed if isinstance(parsed, list) else [parsed]:
                if isinstance(item, list):
                    flat.extend(item)
                else:
                    flat.append(item)
            related_txn_ids = [i for i in flat if isinstance(i, int)]
        except (json.JSONDecodeError, TypeError):
            pass
    if flag.txn_id and flag.txn_id not in related_txn_ids:
        related_txn_ids.append(flag.txn_id)

    account_id = flag.account_id
    txns = []
    for txn_id in related_txn_ids:
        t = session.get(Transaction, txn_id)
        if t:
            txns.append(t)
            account_id = account_id or t.account_id

    classifications = _current_classification_map(session, txns) if txns else {}
    txn_summaries = [
        {
            "id": t.id, "date": t.txn_date.isoformat(), "description": t.description,
            "debit": float(t.debit) if t.debit else None, "credit": float(t.credit) if t.credit else None,
            "balance": float(t.balance) if t.balance else None,
            "category": classifications[t.id].category.value if classifications.get(t.id) else None,
            "classification_reason": classifications[t.id].reason if classifications.get(t.id) else None,
        }
        for t in txns
    ]

    # Light historical context: same-category transactions in the same
    # account over the preceding 6 months, for the LLM to compare against
    # (it does not compute deviation itself - app/pipeline/behavioral.py
    # already did that; this is just descriptive history for narrative).
    historical = []
    if account_id and txns:
        all_account_txns = session.exec(
            select(Transaction).where(Transaction.account_id == account_id)
        ).all()
        all_classifications = _current_classification_map(session, all_account_txns)
        categories_in_case = {c.category for c in classifications.values() if c}
        for t in all_account_txns:
            if t.id in related_txn_ids:
                continue
            cls = all_classifications.get(t.id)
            if cls and cls.category in categories_in_case:
                historical.append({
                    "id": t.id, "date": t.txn_date.isoformat(),
                    "amount": float(t.debit or t.credit or 0), "category": cls.category.value,
                })

    return {
        "case_id": f"FLAG-{flag.id}",
        "flag_type": flag.flag_type,
        "flag_severity": flag.severity.value,
        "flag_message": flag.message,
        "account_id": account_id,
        "related_transactions": txn_summaries,
        "historical_same_category_transactions": sorted(historical, key=lambda h: h["date"])[-20:],
    }


def _deterministic_fallback(evidence: dict, reason: str) -> dict:
    return {
        "observed_facts": evidence["flag_message"],
        "historical_comparison": "Not generated - no LLM provider configured.",
        "supporting_evidence": "", "contradicting_evidence": "",
        "possible_explanations": "",
        "unresolved_questions": "LLM reasoning step did not run: " + reason,
        "recommendation": ReviewRecommendation.NEEDS_INFORMATION.value,
        "confidence": 0.0,
        "escalation_reason": "",
    }


def review_flag(session: Session, flag: Flag, client: LLMClient = None) -> AIReview:
    """
    Runs the AI Reviewer for one Flag and persists the result. Idempotent
    in the sense that it always appends a new AIReview row (append-only,
    matching the rest of this codebase's audit-trail convention) rather
    than overwriting a prior review of the same case.
    """
    client = client or get_default_client()
    evidence = _gather_evidence(session, flag)

    if client.model_name is None:
        output = _deterministic_fallback(evidence, "no ANTHROPIC_API_KEY configured in this environment")
    else:
        user_prompt = (
            "Flagged case:\n" + json.dumps(evidence, indent=2) +
            "\n\nProduce your structured review as specified in the system prompt."
        )
        parsed = client.generate_json(SYSTEM_PROMPT, user_prompt)
        output = parsed if parsed else _deterministic_fallback(evidence, "LLM call failed or returned unparseable output")

    recommendation = output.get("recommendation", ReviewRecommendation.NEEDS_INFORMATION.value)
    if recommendation not in (r.value for r in ReviewRecommendation):
        recommendation = ReviewRecommendation.NEEDS_INFORMATION.value

    # Policy guardrail (ASSUMPTIONS.md A-008): a HIGH-severity flag is never
    # auto-resolvable regardless of what the LLM recommends.
    if flag.severity.value == "high" and recommendation == ReviewRecommendation.LIKELY_LEGITIMATE.value:
        recommendation = ReviewRecommendation.ESCALATE_TO_HUMAN.value
        output["escalation_reason"] = (output.get("escalation_reason") or "") + \
            " Escalated by policy: HIGH-severity flags always require human review."

    review = AIReview(
        case_id=evidence["case_id"],
        flag_id=flag.id,
        account_id=evidence["account_id"],
        triggered_rule=flag.flag_type,
        related_txn_ids=json.dumps([t["id"] for t in evidence["related_transactions"]]),
        observed_facts=str(output.get("observed_facts", "")),
        historical_comparison=str(output.get("historical_comparison", "")),
        supporting_evidence=str(output.get("supporting_evidence", "")),
        contradicting_evidence=str(output.get("contradicting_evidence", "")),
        possible_explanations=str(output.get("possible_explanations", "")),
        unresolved_questions=str(output.get("unresolved_questions", "")),
        recommendation=ReviewRecommendation(recommendation),
        confidence=float(output.get("confidence", 0.0) or 0.0),
        escalation_reason=str(output.get("escalation_reason") or "") or None,
        llm_model_name=client.model_name,
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def review_pending_flags(session: Session, account_id: int = None, limit: int = 50) -> list:
    """
    Runs the AI Reviewer for every Flag that doesn't have an AIReview yet
    (optionally scoped to one account). Called after
    generate_all_flags()/anomalies.run_all() in the pipeline, per the
    handoff's ordering: anomaly detection -> AI Reviewer -> human review.
    Kept as an explicit, separately-triggered step (not run automatically
    on every upload) since it may call out to a paid external API.
    """
    reviewed_flag_ids = {r.flag_id for r in session.exec(select(AIReview)).all() if r.flag_id}
    query = select(Flag)
    if account_id is not None:
        query = query.where(Flag.account_id == account_id)
    pending = [f for f in session.exec(query).all() if f.id not in reviewed_flag_ids][:limit]
    client = get_default_client()
    return [review_flag(session, f, client=client) for f in pending]
