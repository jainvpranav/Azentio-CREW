import json
from datetime import date
from decimal import Decimal as D

from app.models import Flag, FlagSeverity, AIReview, ReviewRecommendation
from app.ai.reviewer import review_flag
from app.ai.llm_client import LLMClient, NullLLMClient


class FakeLLMClient(LLMClient):
    """Returns a canned, well-formed JSON response - stands in for a real API call."""

    def __init__(self, response: dict):
        self._response = response

    def generate_json(self, system_prompt, user_prompt):
        self.last_user_prompt = user_prompt  # inspectable in tests
        return self._response

    @property
    def model_name(self):
        return "fake-model-for-tests"


def test_no_provider_falls_back_to_needs_information(session, make_account, make_txn):
    account = make_account()
    txn = make_txn(account, 1, date(2026, 4, 5), "SUSPICIOUS DEBIT", debit=D("500"))
    flag = Flag(account_id=account.id, txn_id=txn.id, flag_type="TEST_FLAG",
                severity=FlagSeverity.WARN, message="test flag")
    session.add(flag)
    session.commit()
    session.refresh(flag)

    review = review_flag(session, flag, client=NullLLMClient())

    assert review.recommendation == ReviewRecommendation.NEEDS_INFORMATION
    assert review.llm_model_name is None
    assert "no ANTHROPIC_API_KEY" in review.unresolved_questions or "LLM" in review.unresolved_questions


def test_llm_response_is_persisted_with_evidence_grounding(session, make_account, make_txn):
    account = make_account()
    txn = make_txn(account, 1, date(2026, 4, 5), "LARGE CASH DEPOSIT", credit=D("250000"))
    flag = Flag(account_id=account.id, txn_id=txn.id, flag_type="LARGE_CASH_DEPOSIT",
                severity=FlagSeverity.WARN, message="Large cash deposit: review.")
    session.add(flag)
    session.commit()
    session.refresh(flag)

    fake_response = {
        "observed_facts": "A single cash deposit of ₹250000 on 2026-04-05.",
        "historical_comparison": "No prior cash deposits of this size in the account's history.",
        "supporting_evidence": "None found.",
        "contradicting_evidence": "Amount is well above any prior deposit.",
        "possible_explanations": "Sale of an asset, gift, or business cash sales.",
        "unresolved_questions": "Source of funds is not stated in the narration.",
        "recommendation": "NEEDS_INFORMATION",
        "confidence": 0.4,
        "escalation_reason": "",
    }
    client = FakeLLMClient(fake_response)

    review = review_flag(session, flag, client=client)

    assert review.recommendation == ReviewRecommendation.NEEDS_INFORMATION
    assert review.llm_model_name == "fake-model-for-tests"
    assert str(txn.id) in review.related_txn_ids
    # The evidence pack handed to the "LLM" must reference the real txn id,
    # not a fabricated one - grounding check.
    evidence = json.loads(client.last_user_prompt.split("Flagged case:\n", 1)[1].split("\n\nProduce")[0])
    assert evidence["related_transactions"][0]["id"] == txn.id


def test_high_severity_flag_always_escalates_even_if_llm_says_legitimate(session, make_account, make_txn):
    account = make_account()
    txn = make_txn(account, 1, date(2026, 4, 5), "RETURNED PAYMENT", debit=D("1000"))
    flag = Flag(account_id=account.id, txn_id=txn.id, flag_type="RETURNED_PAYMENT",
                severity=FlagSeverity.HIGH, message="Payment returned.")
    session.add(flag)
    session.commit()
    session.refresh(flag)

    client = FakeLLMClient({
        "observed_facts": "x", "historical_comparison": "x", "supporting_evidence": "x",
        "contradicting_evidence": "", "possible_explanations": "x", "unresolved_questions": "",
        "recommendation": "LIKELY_LEGITIMATE", "confidence": 0.9, "escalation_reason": "",
    })

    review = review_flag(session, flag, client=client)

    assert review.recommendation == ReviewRecommendation.ESCALATE_TO_HUMAN
    assert "HIGH-severity" in review.escalation_reason
    assert review.human_decision.value == "pending"
