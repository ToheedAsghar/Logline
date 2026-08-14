"""LLMProvider implementation backed by the `google-genai` SDK.

The schema is sent as raw JSON Schema via `response_json_schema`, not by handing the SDK the pydantic class. That
distinction is load-bearing -- see `run_structured`.
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
    ERROR_RUN_STRUCTURED_CONTENT_FILTERED, ERROR_RUN_STRUCTURED_TRUNCATED, ERROR_RUN_STRUCTURED_VALIDATION_FAILED,
)

logger = logging.getLogger(__name__)

ERROR_GEMINI_RUN_TURN_UNSUPPORTED = (
    "GeminiProvider does not implement run_turn. Gemini is wired for structured output only "
    "(run_structured), which is all the reconciliation pipeline uses."
)
ERROR_GEMINI_TOOL_MESSAGE_UNSUPPORTED = (
    "run_structured failed: GeminiProvider received a role='tool' message, but it does not support "
    "tool calling. Structured-output calls should only carry system/user/assistant messages."
)
ERROR_RUN_STRUCTURED_PROMPT_BLOCKED = (
    "run_structured failed: the prompt was blocked before generation could start (reason: {reason})"
)
ERROR_RUN_STRUCTURED_NO_CANDIDATES = "run_structured failed: the model returned no candidates"
ERROR_RUN_STRUCTURED_EMPTY_TEXT = (
    "run_structured failed: the model returned an empty response body, so there was nothing to "
    "parse into {model_name}"
)
ERROR_GEMINI_API_ERROR = (
    "run_structured failed: the Gemini API request for {model_name} failed (see cause for detail)"
)
GEMINI_USAGE_LOG_FORMAT = "gemini %s usage: prompt=%s candidates=%s total=%s"

REQUEST_TIMEOUT_MS = 60_000

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
            api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)
        )

    async def run_turn(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> AgentResponse:
        """Not supported -- Gemini is wired for structured output only.

        `run_turn` is abstract on `LLMProvider`, so this class has to define it. Raising is the honest option:
        implementing Gemini tool calling here would ship a substantial, completely unexercised code path, since
        nothing that uses Gemini calls tools. A caller that reaches this gets a clear error instead of
        silently-wrong agent behaviour.
        """
        raise NotImplementedError(ERROR_GEMINI_RUN_TURN_UNSUPPORTED)

    async def run_structured(self, messages: list[Message], response_model: type[T]) -> T:
        """Asks Gemini for structured JSON matching `response_model` and validates it before returning.

        Sends raw JSON Schema (`response_json_schema`) so bounds and strict property rules are enforced by the API.
        Validates the response locally with pydantic, raising `LLMStructuredOutputError` on schema mismatches or
        blocked responses. Translates API transport errors into `LLMStructuredOutputError` to prevent sensitive
        prompt leakage.
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
        """Rejects a prompt the API refused before generating anything.

        This is distinct from a blocked candidate: nothing was generated at all, so there are no candidates to
        inspect and the generic no-candidates error would hide the actual reason.
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
        """Rejects candidates that stopped for any reason other than finishing normally.

        Checked before reading `.text`, because a truncated or filtered candidate can still carry a partial body that
        would fail validation with a misleading "didn't match the schema" error instead of the real cause.
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
        """Splits neutral messages into Gemini's (system_instruction, contents) shape.

        Gemini carries system text out-of-band rather than as a turn in the conversation, so system messages are
        pulled out and joined; the rest map to user/model turns.
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
