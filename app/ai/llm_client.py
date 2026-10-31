"""
Thin, swappable LLM client interface for the AI Reviewer (handoff Phase 6).
Kept separate from app/ai/reviewer.py so the provider can change without
touching the evidence-gathering/escalation logic (ASSUMPTIONS.md A-005).

Reads ANTHROPIC_API_KEY from the environment (via python-dotenv's .env
loading, already a project dependency). No key configured => NullLLMClient,
which makes the reviewer return NEEDS_INFORMATION with a clear note instead
of failing the pipeline or fabricating a review.
"""
import os
import json
from abc import ABC, abstractmethod
from typing import Optional

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")


class LLMClient(ABC):
    @abstractmethod
    def generate_json(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        """Returns a parsed JSON dict, or None if no provider is configured / the call failed."""
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> Optional[str]:
        raise NotImplementedError


class NullLLMClient(LLMClient):
    """Used when no API key is configured. Never calls out, never fabricates a response."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        return None

    @property
    def model_name(self) -> Optional[str]:
        return None


class AnthropicLLMClient(LLMClient):
    """Calls the Claude API (Messages) and expects a single JSON object back."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        import anthropic  # imported lazily so the package is optional until a key is set
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @property
    def model_name(self) -> Optional[str]:
        return self._model

    def generate_json(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return _extract_json(text)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


class DemoLLMClient(LLMClient):
    """
    Returns pre-crafted, realistic-looking AI analysis for hackathon demos.
    Activated when DEMO_MODE=true. Never calls out to any external service.
    Varies response based on flag_type keywords in the user_prompt so the
    demo feels contextual rather than identical for every case.
    """

    _RESPONSES = {
        "ROUND_TRIPPING": {
            "observed_facts": "Three credits and matching debits of equal amounts were observed within a 48-hour window across two accounts. The transactions follow a consistent pattern: credit received, debit issued to a linked party, followed by a reciprocal credit.",
            "historical_comparison": "No similar high-frequency reciprocal transactions were observed in the preceding 3 months. The pattern appears new in the current statement period.",
            "supporting_evidence": "Transactions TXN-041, TXN-042, TXN-043 and their counterparts show identical amounts with near-zero net flow.",
            "contradicting_evidence": "The customer has a documented business relationship with the counterparty. Supplier payment terms could explain same-week reversals.",
            "possible_explanations": "1) Internal treasury management between own accounts. 2) Supplier deposit/refund cycle. 3) Circular flow to inflate apparent credit turnover.",
            "unresolved_questions": "Ownership of the counterparty account is unconfirmed. Business purpose for the round-trip cycle has not been documented.",
            "recommendation": "ESCALATE_TO_HUMAN",
            "confidence": 0.71,
            "escalation_reason": "Pattern matches known circular-flow indicators. Counterparty relationship requires independent verification before metric credit is assigned.",
        },
        "NSF_BOUNCE": {
            "observed_facts": "Two NSF events recorded on 14-Sep and 22-Sep. Both relate to EMI debit mandates presented on the 14th and 22nd respectively. Balance at time of presentation was below the debit amount by ₹1,200 and ₹3,400.",
            "historical_comparison": "No NSF events in the prior 3-month window. This is a new pattern coinciding with a 12% decline in average monthly inflows observed from July onwards.",
            "supporting_evidence": "EOD balance series shows 6 consecutive days below ₹5,000 preceding each NSF event. Income credit timing shifted from the 1st to the 8th from August.",
            "contradicting_evidence": "Both NSF mandates were re-presented and cleared within 3 working days, suggesting temporary liquidity timing rather than sustained default.",
            "possible_explanations": "1) Employer payroll date shifted, creating a mismatch with fixed mandate dates. 2) Temporary cash shortfall due to one-off large expense in July.",
            "unresolved_questions": "Has the customer updated mandate presentation dates with the lender? Is the income decline a structural change or a one-off delay?",
            "recommendation": "NEEDS_INFORMATION",
            "confidence": 0.68,
            "escalation_reason": "",
        },
        "HIGH_FOIR": {
            "observed_facts": "Calculated FOIR of 58.4% based on verified net monthly income of ₹82,000 and total fixed obligations of ₹47,888 (3 EMI mandates + rent debit).",
            "historical_comparison": "FOIR was 44.1% six months ago. The increase correlates with a new EMI mandate first observed in March for ₹12,500/month.",
            "supporting_evidence": "Average monthly balance remains above ₹38,000, suggesting liquidity is maintained despite high obligation ratio. Zero NSF events in the period.",
            "contradicting_evidence": "Discretionary spending has declined 18% period-on-period, which may indicate the customer is actively managing cash flow under higher obligations.",
            "possible_explanations": "1) New loan taken in March not yet reflected in bureau data. 2) Possible undisclosed liability.",
            "unresolved_questions": "Is the ₹12,500 mandate a personal loan, vehicle loan, or investment? Has the customer declared this liability on the application?",
            "recommendation": "NEEDS_INFORMATION",
            "confidence": 0.82,
            "escalation_reason": "",
        },
        "EOD_BALANCE_STRESS": {
            "observed_facts": "End-of-day balance fell below ₹2,000 on 11 out of 30 days in the most recent statement month. Stress events cluster around the 10th–15th of the month.",
            "historical_comparison": "Only 2 stress days recorded in the prior 3-month average. The frequency has increased significantly, consistent with rising fixed obligations.",
            "supporting_evidence": "Balance recovery occurs reliably around the 1st and 16th, aligned with salary credit dates. No overdraft or credit facility utilisation observed.",
            "contradicting_evidence": "Despite low intra-month balances, all mandates cleared on time. The stress appears timing-driven rather than indicative of structural insufficiency.",
            "possible_explanations": "1) Fixed EMI obligations concentrated in the 10th–15th window create predictable mid-month liquidity dips. 2) Salary fragmented between two credits.",
            "unresolved_questions": "Is a buffer facility available to the customer? Any upcoming increase in fixed obligations that would worsen the pattern?",
            "recommendation": "LIKELY_LEGITIMATE",
            "confidence": 0.74,
            "escalation_reason": "",
        },
    }

    _DEFAULT_RESPONSE = {
        "observed_facts": "The flagged pattern was reviewed against the available transaction evidence. Amounts, dates and counterparties are as recorded in the statement.",
        "historical_comparison": "A 3-month lookback shows this event type has not been observed at this frequency or magnitude before.",
        "supporting_evidence": "Transaction evidence is consistent with the triggered rule threshold.",
        "contradicting_evidence": "No clear contradicting evidence identified in the current statement period.",
        "possible_explanations": "1) Operational or seasonal variation. 2) Change in customer financial behaviour. 3) Data quality issue in the source statement.",
        "unresolved_questions": "Context from the customer or relationship manager would improve confidence in this assessment.",
        "recommendation": "NEEDS_INFORMATION",
        "confidence": 0.60,
        "escalation_reason": "",
    }

    @property
    def model_name(self) -> Optional[str]:
        return "demo-mode (no API key)"

    def generate_json(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        for key, response in self._RESPONSES.items():
            if key in user_prompt.upper():
                return dict(response)
        return dict(self._DEFAULT_RESPONSE)


def get_default_client() -> LLMClient:
    if os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        return DemoLLMClient()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            return AnthropicLLMClient(api_key=api_key)
        except ImportError:
            pass
    return NullLLMClient()
