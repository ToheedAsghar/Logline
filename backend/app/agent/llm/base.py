"""Provider-agnostic types for the agent's LLM boundary.

Everything in this file is neutral with respect to which LLM API is actually driving the agent. This module must
never import `openai` or `anthropic` directly — provider-specific conversion logic belongs in the individual
provider modules (e.g. app/agent/llm/openai_provider.py).
"""

from abc import ABC
from dataclasses import dataclass
from typing import Literal, Optional, TypeVar

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]

T = TypeVar("T", bound=BaseModel)


@dataclass
class Message:
    """One turn in the conversation."""

    role: Role
    content: Optional[str] = None


class LLMResponseError(Exception):
    """Raised when a provider fails to produce a usable response, for any reason not specific to structured output."""


class LLMStructuredOutputError(LLMResponseError):
    """Raised when a provider fails to produce valid structured output.

    Carries the target schema's name and the original underlying error (if any),
    so callers/logs can inspect what actually went wrong without parsing the
    message string.
    """

    def __init__(self, message: str, *, response_model_name: str | None = None, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.response_model_name = response_model_name
        self.cause = cause


class LLMProvider(ABC):
    """Abstract boundary callers talk to — never a concrete SDK."""

    async def run_structured(self, messages: list[Message], response_model: type[T]) -> T:
        """Send one turn to the model and parse its response into `response_model`.

        Concrete default (not `@abstractmethod`) raises `NotImplementedError` for a provider that doesn't
        override it. Providers that support structured output (e.g. OpenAIProvider) override this.
        """
        raise NotImplementedError("run_structured not implemented by this provider")
