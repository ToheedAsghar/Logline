"""Provider-agnostic types for the agent's LLM boundary.

Everything in this file is neutral with respect to which LLM API is actually
driving the agent. This module (and app/agent/runner.py, app/agent/toolbelt.py)
must never import `openai` or `anthropic` directly — provider-specific
conversion logic belongs in the individual provider modules
(e.g. app/agent/llm/openai_provider.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypeVar

from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "tool"]

T = TypeVar("T", bound=BaseModel)


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """One turn in the conversation.

    `tool_calls` is populated on assistant messages that requested tool use.
    `tool_call_id` is populated on role="tool" messages to tie a result back
    to the ToolCall.id it answers.
    """

    role: Role
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None


@dataclass
class ToolDefinition:
    """A tool the model may call, described with a plain JSON-schema dict."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class AgentResponse:
    """The model's output for one turn."""

    text: Optional[str]
    tool_calls: list[ToolCall]
    is_final: bool


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
    """Abstract boundary the runner talks to — never a concrete SDK."""

    @abstractmethod
    async def run_turn(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> AgentResponse:
        """Send one turn to the model and return its neutral response."""

    async def run_structured(self, messages: list[Message], response_model: type[T]) -> T:
        """Send one turn to the model and parse its response into `response_model`.

        Concrete default (not `@abstractmethod`) so existing fake providers
        that only implement `run_turn` keep working untouched. Providers that
        support structured output (e.g. OpenAIProvider) override this.
        """
        raise NotImplementedError("run_structured not implemented by this provider")
