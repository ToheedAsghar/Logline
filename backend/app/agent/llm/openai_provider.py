"""LLMProvider implementation backed by the `openai` SDK.

All OpenAI-specific shapes (function-calling schema, chat message format,
`finish_reason`/`tool_calls` parsing) are converted to and from our neutral
types here. Nothing outside this module should need to know these details.
"""

import json
import logging
from typing import Any

import openai
import pydantic
from openai import AsyncOpenAI

from app.agent.llm.base import (
    AgentResponse, LLMProvider, LLMResponseError, LLMStructuredOutputError, Message, T, ToolCall, ToolDefinition,
)
from app.agent.llm.constants import (
    ERROR_RUN_STRUCTURED_CONTENT_FILTERED, ERROR_RUN_STRUCTURED_PARSED_NONE, ERROR_RUN_STRUCTURED_TRUNCATED,
    ERROR_RUN_STRUCTURED_VALIDATION_FAILED, ERROR_RUN_STRUCTURED_ZERO_CHOICES, ERROR_RUN_TURN_ZERO_CHOICES,
    LLM_USAGE_EVENT,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key)

    async def run_turn(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> AgentResponse:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages),
            tools=self._to_openai_tools(tools) if tools else None,
        )

        if not response.choices:
            raise LLMResponseError(ERROR_RUN_TURN_ZERO_CHOICES)

        self._log_usage("run_turn", response)

        choice = response.choices[0]
        raw_tool_calls = choice.message.tool_calls or []
        tool_calls = [
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}"),
            )
            for call in raw_tool_calls
        ]

        return AgentResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            is_final=len(tool_calls) == 0,
        )

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
    def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    @staticmethod
    def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
        openai_messages: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content or "",
                    }
                )
                continue

            entry: dict[str, Any] = {"role": message.role}
            if message.content is not None:
                entry["content"] = message.content
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in message.tool_calls
                ]
            openai_messages.append(entry)
        return openai_messages
