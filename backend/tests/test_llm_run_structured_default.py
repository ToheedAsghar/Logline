"""
Tests for `LLMProvider.run_structured`'s base-class default (app/agent/llm/base.py).

`run_structured` is a concrete method (not `@abstractmethod`) with a default
body that raises `NotImplementedError`. It's deliberately not abstract so the
existing fake providers used by test_agent_runner_created_entry_id.py,
test_calendar_location_exclusion.py, and test_slack_channel_fallback.py --
which only implement `run_turn` -- keep working unchanged. Providers that do
support structured output (e.g. OpenAIProvider) override it.

These tests confirm both halves of that contract: a provider that overrides
`run_structured` never falls through to the base default, and a provider
that doesn't override it gets the `NotImplementedError` from the base class.
"""

import asyncio

import pytest
from pydantic import BaseModel

from app.agent.llm.base import AgentResponse, LLMProvider, Message


class _Animal(BaseModel):
    name: str
    legs: int


class _OverridingProvider(LLMProvider):
    """Overrides run_structured to return a scripted instance directly."""

    async def run_turn(self, messages, tools) -> AgentResponse:
        raise NotImplementedError("not exercised by this test")

    async def run_structured(self, messages, response_model):
        return response_model(name="dog", legs=4)


class _RunTurnOnlyProvider(LLMProvider):
    """Mirrors the existing fake providers: only implements run_turn."""

    async def run_turn(self, messages, tools) -> AgentResponse:
        return AgentResponse(text="done", tool_calls=[], is_final=True)


class TestRunStructuredDefault:
    def test_overriding_provider_returns_its_own_value_not_the_base_default(self):
        provider = _OverridingProvider()
        messages = [Message(role="user", content="describe a dog")]

        result = asyncio.run(provider.run_structured(messages, _Animal))

        assert isinstance(result, _Animal)
        assert result == _Animal(name="dog", legs=4)

    def test_provider_without_override_raises_not_implemented_from_base(self):
        provider = _RunTurnOnlyProvider()
        messages = [Message(role="user", content="describe a dog")]

        with pytest.raises(NotImplementedError, match="run_structured not implemented"):
            asyncio.run(provider.run_structured(messages, _Animal))
