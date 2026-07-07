"""LLMProvider implementation backed by the `openai` SDK.

All OpenAI-specific shapes (function-calling schema, chat message format,
`finish_reason`/`tool_calls` parsing) are converted to and from our neutral
types here. Nothing outside this module should need to know these details.
"""

import json
from typing import Any, Optional

from openai import AsyncOpenAI

from app.agent.llm.base import AgentResponse, LLMProvider, Message, ToolCall, ToolDefinition


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
