"""
Tests for `OpenAIProvider.run_structured` (app/agent/llm/openai_provider.py).

`run_structured` calls `self._client.chat.completions.parse(...)` and returns
`completion.choices[0].message.parsed`. Several failure modes are caught and
re-raised as `LLMStructuredOutputError` so callers only ever see our neutral
exception type, never an SDK-specific one:

  - `openai.LengthFinishReasonError` (truncated output)
  - `openai.ContentFilterFinishReasonError` (blocked by content filter)
  - `pydantic.ValidationError` (the parsed JSON didn't match the schema --
    shouldn't normally happen under strict mode, but isn't guaranteed
    impossible by the SDK)
  - zero choices returned by the API
  - `.parsed` being None with no exception raised (the SDK couldn't
    reconcile the output with the schema for a reason that doesn't map to
    either finish-reason error above)

Every raised `LLMStructuredOutputError` should carry `response_model_name`
(and `cause`, where a real underlying exception exists) so callers can
inspect what went wrong without parsing the message string.

The OpenAI client is mocked throughout; no real API calls are made here (see
scripts/ for the separate live model-compatibility check).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import openai
import pydantic
import pytest
from pydantic import BaseModel

from app.agent.llm.base import LLMStructuredOutputError, Message
from app.agent.llm.openai_provider import OpenAIProvider


class _Animal(BaseModel):
    name: str
    legs: int


def _make_provider() -> OpenAIProvider:
    provider = OpenAIProvider(model="gpt-5-mini", api_key="test-key")
    provider._client = MagicMock()
    return provider


def _real_validation_error() -> pydantic.ValidationError:
    """Build a genuine pydantic.ValidationError by actually failing validation,
    rather than hand-constructing one -- so the test exercises the real
    exception shape the SDK would actually raise, not a stand-in."""
    try:
        _Animal.model_validate({"name": "dog", "legs": "not-a-number"})
    except pydantic.ValidationError as exc:
        return exc
    raise AssertionError("expected validation to fail")


class TestOpenAIProviderRunStructured:
    def test_returns_parsed_instance_from_completion(self):
        provider = _make_provider()
        parsed = _Animal(name="dog", legs=4)
        completion = MagicMock()
        completion.choices[0].message.parsed = parsed
        provider._client.chat.completions.parse = AsyncMock(return_value=completion)

        result = asyncio.run(
            provider.run_structured([Message(role="user", content="describe a dog")], _Animal)
        )

        assert result is parsed
        provider._client.chat.completions.parse.assert_awaited_once()
        _, kwargs = provider._client.chat.completions.parse.call_args
        assert kwargs["model"] == "gpt-5-mini"
        assert kwargs["response_format"] is _Animal

    def test_wraps_length_finish_reason_error(self):
        provider = _make_provider()
        provider._client.chat.completions.parse = AsyncMock(
            side_effect=openai.LengthFinishReasonError(completion=MagicMock())
        )

        with pytest.raises(LLMStructuredOutputError, match="truncated") as exc_info:
            asyncio.run(
                provider.run_structured([Message(role="user", content="hi")], _Animal)
            )

        assert exc_info.value.response_model_name == "_Animal"
        assert isinstance(exc_info.value.cause, openai.LengthFinishReasonError)

    def test_wraps_content_filter_finish_reason_error(self):
        provider = _make_provider()
        provider._client.chat.completions.parse = AsyncMock(
            side_effect=openai.ContentFilterFinishReasonError()
        )

        with pytest.raises(LLMStructuredOutputError, match="content filter") as exc_info:
            asyncio.run(
                provider.run_structured([Message(role="user", content="hi")], _Animal)
            )

        assert exc_info.value.response_model_name == "_Animal"
        assert isinstance(exc_info.value.cause, openai.ContentFilterFinishReasonError)

    def test_wraps_pydantic_validation_error(self):
        provider = _make_provider()
        provider._client.chat.completions.parse = AsyncMock(
            side_effect=_real_validation_error()
        )

        with pytest.raises(LLMStructuredOutputError, match="_Animal") as exc_info:
            asyncio.run(
                provider.run_structured([Message(role="user", content="hi")], _Animal)
            )

        assert exc_info.value.response_model_name == "_Animal"
        assert isinstance(exc_info.value.cause, pydantic.ValidationError)

    def test_raises_on_zero_choices(self):
        provider = _make_provider()
        completion = MagicMock()
        completion.choices = []
        provider._client.chat.completions.parse = AsyncMock(return_value=completion)

        with pytest.raises(LLMStructuredOutputError, match="zero choices") as exc_info:
            asyncio.run(
                provider.run_structured([Message(role="user", content="hi")], _Animal)
            )

        assert exc_info.value.response_model_name == "_Animal"
        assert exc_info.value.cause is None

    def test_raises_when_parsed_is_none_without_exception(self):
        """The one silent-failure case: the SDK returns a completion with no
        error, but .parsed is None -- e.g. the model's raw output didn't
        reconcile with the schema in a way that doesn't map to either
        finish-reason error. Must not silently return None as if it were T."""
        provider = _make_provider()
        completion = MagicMock()
        completion.choices[0].message.parsed = None
        provider._client.chat.completions.parse = AsyncMock(return_value=completion)

        with pytest.raises(LLMStructuredOutputError, match="_Animal") as exc_info:
            asyncio.run(
                provider.run_structured([Message(role="user", content="hi")], _Animal)
            )

        assert exc_info.value.response_model_name == "_Animal"
        assert exc_info.value.cause is None
