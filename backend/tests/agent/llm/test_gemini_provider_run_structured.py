"""Tests for `GeminiProvider.run_structured` (app/agent/llm/gemini_provider.py).

`run_structured` sends the target schema as raw JSON Schema via `response_json_schema` and validates the response body
with pydantic before returning it. Failure modes are translated into `LLMStructuredOutputError` so callers only ever
see our neutral exception type, never an SDK one:

  - prompt blocked before generation (`prompt_feedback.block_reason`)
  - zero candidates returned
  - `finish_reason` MAX_TOKENS (truncated) or a safety/blocklist reason (filtered)
  - an empty response body
  - `pydantic.ValidationError` -- including extra keys, since the schemas set `extra="forbid"`
  - `errors.APIError` (auth, quota, 5xx) -- Gemini's `APIError.__str__` can embed the raw request payload (including
    the system prompt), so it is wrapped rather than left to propagate as-is

Using `response_json_schema` over `response_schema`: `google.genai.types.Schema` rejects `exclusiveMinimum` (from
`Field(gt=0)`) and fails on `additional_properties`. `test_sends_schema_unmodified_via_response_json_schema` and
`test_schema_with_gt_constraint_is_sent_intact` guard against regressions to `response_schema`.

The Gemini client is mocked throughout; no real API calls are made here.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pydantic
import pytest
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from app.agent.llm.base import LLMStructuredOutputError, Message
from app.agent.llm.gemini_provider import GeminiProvider


class _Animal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    legs: int = Field(gt=0)


def _make_provider() -> GeminiProvider:
    provider = GeminiProvider(model="gemini-2.5-flash", api_key="test-key")
    provider._client = MagicMock()
    return provider


def _make_response(
    text: str | None = '{"name": "dog", "legs": 4}',
    finish_reason=types.FinishReason.STOP,
    candidates_present: bool = True,
    block_reason=None,
):
    """Builds a mock generate_content response.

    MagicMock's auto-attributes would make every `getattr` probe in the provider look truthy, so the fields the
    provider actually branches on are set explicitly.
    """
    response = MagicMock()
    response.text = text
    response.prompt_feedback = MagicMock(block_reason=block_reason)
    if candidates_present:
        response.candidates = [MagicMock(finish_reason=finish_reason)]
    else:
        response.candidates = []
    return response


def _run(provider: GeminiProvider, model=_Animal):
    return asyncio.run(provider.run_structured([Message(role="user", content="describe a dog")], model))


class TestGeminiProviderClientConfig:
    def test_client_has_explicit_timeout(self):
        """Verifies the constructor sets an explicit timeout on the underlying client.

        An unconfigured client has no timeout, letting a stalled request block the async worker indefinitely.
        """
        provider = GeminiProvider(model="gemini-2.5-flash", api_key="test-key")

        configured_timeout = provider._client._api_client._http_options.timeout

        assert configured_timeout is not None
        assert configured_timeout > 0


class TestGeminiProviderRunStructured:
    def test_returns_validated_instance_from_response_text(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(return_value=_make_response())

        result = _run(provider)

        assert isinstance(result, _Animal)
        assert result.name == "dog"
        assert result.legs == 4

    def test_sends_schema_unmodified_via_response_json_schema(self):
        """Verifies that the raw pydantic schema is sent untouched via `response_json_schema`.

        Sending it as `response_schema` instead would strip `additionalProperties` and fail on numeric bounds,
        silently weakening what the API enforces.
        """
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(return_value=_make_response())

        _run(provider)

        _, kwargs = provider._client.aio.models.generate_content.call_args
        assert kwargs["model"] == "gemini-2.5-flash"
        config = kwargs["config"]
        assert config.response_mime_type == "application/json"
        assert config.response_json_schema == _Animal.model_json_schema()
        assert config.response_schema is None

    def test_schema_with_gt_constraint_is_sent_intact(self):
        """Verifies that `Field(gt=0)` becomes `exclusiveMinimum`, which `response_json_schema` preserves."""
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(return_value=_make_response())

        _run(provider)

        schema = provider._client.aio.models.generate_content.call_args.kwargs["config"].response_json_schema
        assert schema["properties"]["legs"]["exclusiveMinimum"] == 0
        assert schema["additionalProperties"] is False

    def test_nested_model_schema_keeps_defs(self):
        class _Herd(BaseModel):
            model_config = ConfigDict(extra="forbid")

            animals: list[_Animal]

        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text='{"animals": [{"name": "cow", "legs": 4}]}')
        )

        result = asyncio.run(provider.run_structured([Message(role="user", content="herd")], _Herd))

        assert len(result.animals) == 1
        schema = provider._client.aio.models.generate_content.call_args.kwargs["config"].response_json_schema
        assert "_Animal" in schema["$defs"]
        assert schema["$defs"]["_Animal"]["additionalProperties"] is False

    def test_system_messages_become_system_instruction(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(return_value=_make_response())

        asyncio.run(
            provider.run_structured(
                [
                    Message(role="system", content="be terse"),
                    Message(role="system", content="use JSON"),
                    Message(role="user", content="describe a dog"),
                    Message(role="assistant", content="ok"),
                ],
                _Animal,
            )
        )

        kwargs = provider._client.aio.models.generate_content.call_args.kwargs
        assert kwargs["config"].system_instruction == "be terse\n\nuse JSON"
        contents = kwargs["contents"]
        assert [c.role for c in contents] == ["user", "model"]
        assert contents[0].parts[0].text == "describe a dog"

    def test_no_system_message_leaves_system_instruction_unset(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(return_value=_make_response())

        _run(provider)

        assert provider._client.aio.models.generate_content.call_args.kwargs["config"].system_instruction is None

    # --- failure modes ---

    def test_wraps_validation_error(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text='{"name": "dog", "legs": "four"}')
        )

        with pytest.raises(LLMStructuredOutputError, match="_Animal") as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"
        assert isinstance(exc_info.value.cause, pydantic.ValidationError)

    def test_rejects_extra_keys_despite_schema_being_sent_to_the_api(self):
        """Verifies that `extra="forbid"` is enforced locally even when passed to the API.

        A schema accepted by the API is not a guarantee it obeys it, so an extra key fails closed locally rather than
        slipping through.
        """
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text='{"name": "dog", "legs": 4, "wings": 2}')
        )

        with pytest.raises(LLMStructuredOutputError) as exc_info:
            _run(provider)

        assert isinstance(exc_info.value.cause, pydantic.ValidationError)
        assert "wings" in str(exc_info.value)

    def test_rejects_constraint_violation(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text='{"name": "dog", "legs": 0}')
        )

        with pytest.raises(LLMStructuredOutputError) as exc_info:
            _run(provider)

        assert isinstance(exc_info.value.cause, pydantic.ValidationError)

    def test_raises_on_truncated_output(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text='{"name": "do', finish_reason=types.FinishReason.MAX_TOKENS)
        )

        with pytest.raises(LLMStructuredOutputError, match="truncated") as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"

    @pytest.mark.parametrize(
        "finish_reason",
        [types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT, types.FinishReason.BLOCKLIST],
    )
    def test_raises_on_blocked_finish_reason(self, finish_reason):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text=None, finish_reason=finish_reason)
        )

        with pytest.raises(LLMStructuredOutputError, match="content filter") as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"

    def test_raises_on_blocked_prompt(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text=None, candidates_present=False, block_reason="SAFETY")
        )

        with pytest.raises(LLMStructuredOutputError, match="blocked before generation") as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"

    def test_raises_on_zero_candidates(self):
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text=None, candidates_present=False)
        )

        with pytest.raises(LLMStructuredOutputError, match="no candidates") as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"
        assert exc_info.value.cause is None

    def test_raises_on_empty_body(self):
        """Verifies that an empty response body raises an error instead of a confusing validation error."""
        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(return_value=_make_response(text=""))

        with pytest.raises(LLMStructuredOutputError, match="empty response body") as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"
        assert exc_info.value.cause is None

    def test_api_errors_are_wrapped(self):
        """Verifies that API errors are wrapped to prevent raw request payload and prompt leakage."""
        from google.genai import errors

        provider = _make_provider()
        underlying = errors.ClientError(429, {"error": {"message": "quota exceeded"}})
        provider._client.aio.models.generate_content = AsyncMock(side_effect=underlying)

        with pytest.raises(LLMStructuredOutputError) as exc_info:
            _run(provider)

        assert exc_info.value.response_model_name == "_Animal"
        assert exc_info.value.cause is underlying

    def test_server_api_errors_are_also_wrapped(self):
        """Verifies that `ServerError` (5xx) is wrapped to prevent payload and prompt leakage."""
        from google.genai import errors

        provider = _make_provider()
        provider._client.aio.models.generate_content = AsyncMock(
            side_effect=errors.ServerError(503, {"error": {"message": "unavailable"}})
        )

        with pytest.raises(LLMStructuredOutputError):
            _run(provider)
