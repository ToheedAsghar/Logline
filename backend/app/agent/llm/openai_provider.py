"""LLMProvider implementation backed by the `openai` SDK.

All OpenAI-specific shapes (chat message format, structured-output parsing) are converted to and from our neutral
types here. Nothing outside this module should need to know these details.
"""

import logging
from typing import Any

import openai
import pydantic
from openai import AsyncOpenAI

from app.agent.llm.base import LLMProvider, LLMStructuredOutputError, Message, T
from app.agent.llm.constants import (
    ERROR_RUN_STRUCTURED_CONTENT_FILTERED, ERROR_RUN_STRUCTURED_TRUNCATED, ERROR_RUN_STRUCTURED_VALIDATION_FAILED,
    LLM_USAGE_EVENT,
)

logger = logging.getLogger(__name__)

ERROR_RUN_STRUCTURED_ZERO_CHOICES = "run_structured failed: the model returned zero choices"
ERROR_RUN_STRUCTURED_PARSED_NONE = (
    "run_structured failed: the model's response could not be parsed into {model_name} "
    "(no exception was raised, but .parsed was None)"
)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key)

    async def run_structured(self, messages: list[Message], response_model: type[T]) -> T:
        try:
            completion = await self._client.chat.completions.parse(
                model=self.model,
                messages=self._to_openai_messages(messages),
                response_format=response_model,
            )
        except openai.LengthFinishReasonError as exc:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_TRUNCATED,
                response_model_name=response_model.__name__,
                cause=exc,
            ) from exc
        except openai.ContentFilterFinishReasonError as exc:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_CONTENT_FILTERED,
                response_model_name=response_model.__name__,
                cause=exc,
            ) from exc
        except pydantic.ValidationError as exc:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_VALIDATION_FAILED.format(
                    model_name=response_model.__name__, detail=exc
                ),
                response_model_name=response_model.__name__,
                cause=exc,
            ) from exc

        if not completion.choices:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_ZERO_CHOICES, response_model_name=response_model.__name__
            )

        self._log_usage("run_structured", completion)

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise LLMStructuredOutputError(
                ERROR_RUN_STRUCTURED_PARSED_NONE.format(model_name=response_model.__name__),
                response_model_name=response_model.__name__,
            )

        return parsed

    @staticmethod
    def _log_usage(call_kind: str, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        logger.info(
            LLM_USAGE_EVENT,
            extra={
                "provider": "openai",
                "call_kind": call_kind,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        )

    @staticmethod
    def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
        openai_messages: list[dict[str, Any]] = []
        for message in messages:
            entry: dict[str, Any] = {"role": message.role}
            if message.content is not None:
                entry["content"] = message.content
            openai_messages.append(entry)
        return openai_messages
