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


def get_default_client() -> LLMClient:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return NullLLMClient()
    try:
        return AnthropicLLMClient(api_key=api_key)
    except ImportError:
        return NullLLMClient()
