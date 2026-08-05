"""LLMProvider implementation backed by the `google-genai` SDK.

Structured output only. `run_turn` is deliberately unimplemented: the reconciliation pipeline --
the only thing that needs Gemini -- never lets the model call tools. Code decides what to fetch and
match; the model only turns an already-built evidence bundle into a structured draft. Tool calling
belongs to the older agent runner, which stays OpenAI-only. See `run_turn` below.

The schema is sent as raw JSON Schema via `response_json_schema`, not by handing the SDK the pydantic
class. That distinction is load-bearing -- see `run_structured`.
"""

import logging
from typing import Any, Optional

import pydantic
from google import genai
from google.genai import errors, types

from app.agent.llm.base import (
    AgentResponse, LLMProvider, LLMResponseError, LLMStructuredOutputError, Message, T, ToolDefinition,
)
from app.agent.llm.constants import (
    ERROR_GEMINI_API_ERROR, ERROR_GEMINI_RUN_TURN_UNSUPPORTED, ERROR_GEMINI_TOOL_MESSAGE_UNSUPPORTED,
    ERROR_RUN_STRUCTURED_CONTENT_FILTERED, ERROR_RUN_STRUCTURED_EMPTY_TEXT, ERROR_RUN_STRUCTURED_NO_CANDIDATES,
    ERROR_RUN_STRUCTURED_PROMPT_BLOCKED, ERROR_RUN_STRUCTURED_TRUNCATED, ERROR_RUN_STRUCTURED_VALIDATION_FAILED,
    GEMINI_USAGE_LOG_FORMAT,
)

logger = logging.getLogger(__name__)

# Bounds a stalled request on Gemini's end so it can't block an async worker indefinitely. This is
# a structured-output call on a background pipeline (not a request the user is blocked on), so a
# generous ceiling is fine; 60s is well above observed real-call latency while still bounded.
_REQUEST_TIMEOUT_MS = 60_000

# Finish reasons that mean the model refused or was cut off by a safety system rather than
# finishing normally. MAX_TOKENS is handled separately -- truncation is a size problem, not a
# refusal, and callers may want to react differently.
BLOCKED_FINISH_REASONS = frozenset(
    {
        types.FinishReason.SAFETY,
        types.FinishReason.RECITATION,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.SPII,
    }
)


class GeminiProvider(LLMProvider):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS)
        )

    async def run_turn(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> AgentResponse:
        """Not supported -- Gemini is wired for structured output only.

        `run_turn` is abstract on `LLMProvider`, so this class has to define it. Raising is the
        honest option: implementing Gemini tool calling here would ship a substantial, completely
        unexercised code path, since nothing that uses Gemini calls tools. A caller that reaches
        this gets a clear error instead of silently-wrong agent behaviour.
        """
        raise NotImplementedError(ERROR_GEMINI_RUN_TURN_UNSUPPORTED)

    async def run_structured(self, messages: list[Message], response_model: type[T]) -> T:
        """Ask Gemini for JSON matching `response_model` and validate it before returning.

        The schema goes over the wire as raw JSON Schema (`response_json_schema`) rather than by
        passing the pydantic class as `response_schema`. The two paths are not equivalent: the
        `response_schema` path converts through `google.genai.types.Schema`, which rejects
        `exclusiveMinimum` (emitted by `Field(gt=0)`) outright and whose `additional_properties` the
        API then refuses. `response_json_schema` accepts our schemas untouched, so
        `additionalProperties: false` from `extra="forbid"` and the numeric bounds are enforced by
        the API rather than quietly dropped.

        The response is still validated locally with pydantic: `response_json_schema` populates
        `.parsed` with a plain dict, and a schema the API honours is not the same as one it
        guarantees, so nothing is trusted until it validates. Any mismatch fails closed as
        `LLMStructuredOutputError`.

        API-level failures (auth, quota, 5xx) are also translated into `LLMStructuredOutputError`,
        unlike `OpenAIProvider`, which lets its transport errors through untouched: a 400-level
        `errors.APIError` can embed the raw request payload -- including the system prompt -- in its
        string representation, so it must not propagate as-is to anything that might log or surface
        it verbatim.
        """
        system_instruction, contents = self._to_gemini_contents(messages)

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=response_model.model_json_schema(),
                ),
            )
        except errors.APIError as exc:
            raise LLMStructuredOutputError(
                ERROR_GEMINI_API_ERROR.format(model_name=response_model.__name__),
                response_model_name=response_model.__name__,
                cause=exc,
            ) from exc

        self._raise_for_blocked_prompt(response, response_model)

        candidates = response.candidates or []
        if not candidates:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_NO_CANDIDATES, response_model_name=response_model.__name__
            )

        self._raise_for_finish_reason(candidates[0].finish_reason, response_model)
        self._log_usage("run_structured", response)

        text = response.text
        if not text:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_EMPTY_TEXT.format(model_name=response_model.__name__),
                response_model_name=response_model.__name__,
            )

        try:
            return response_model.model_validate_json(text)
        except pydantic.ValidationError as exc:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_VALIDATION_FAILED.format(
                    model_name=response_model.__name__, detail=exc
                ),
                response_model_name=response_model.__name__,
                cause=exc,
            ) from exc

    @staticmethod
    def _raise_for_blocked_prompt(response: Any, response_model: type[T]) -> None:
        """Reject a prompt the API refused before generating anything.

        This is distinct from a blocked candidate: nothing was generated at all, so there are no
        candidates to inspect and the generic no-candidates error would hide the actual reason.
        """
        feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(feedback, "block_reason", None) if feedback is not None else None
        if block_reason is None:
            return
        raise LLMStructuredOutputError(
            ERROR_RUN_STRUCTURED_PROMPT_BLOCKED.format(reason=block_reason),
            response_model_name=response_model.__name__,
        )

    @staticmethod
    def _raise_for_finish_reason(finish_reason: Any, response_model: type[T]) -> None:
        """Reject candidates that stopped for any reason other than finishing normally.

        Checked before reading `.text`, because a truncated or filtered candidate can still carry a
        partial body that would fail validation with a misleading "didn't match the schema" error
        instead of the real cause.
        """
        if finish_reason == types.FinishReason.MAX_TOKENS:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_TRUNCATED, response_model_name=response_model.__name__
            )
        if finish_reason in BLOCKED_FINISH_REASONS:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_CONTENT_FILTERED, response_model_name=response_model.__name__
            )

    @staticmethod
    def _log_usage(call_kind: str, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        logger.info(
            GEMINI_USAGE_LOG_FORMAT, call_kind, getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None), getattr(usage, "total_token_count", None),
        )

    @staticmethod
    def _to_gemini_contents(messages: list[Message]) -> tuple[Optional[str], list[types.Content]]:
        """Split our neutral messages into Gemini's (system_instruction, contents) shape.

        Gemini carries system text out-of-band rather than as a turn in the conversation, so system
        messages are pulled out and joined; the rest map to user/model turns.
        """
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for message in messages:
            if message.role == "system":
                if message.content:
                    system_parts.append(message.content)
                continue
            if message.role == "tool":
                raise LLMResponseError(ERROR_GEMINI_TOOL_MESSAGE_UNSUPPORTED)

            contents.append(
                types.Content(
                    role="model" if message.role == "assistant" else "user",
                    parts=[types.Part(text=message.content or "")],
                )
            )

        return ("\n\n".join(system_parts) if system_parts else None), contents
