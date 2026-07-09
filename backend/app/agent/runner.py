"""Main agent orchestration loop.

Given a user and a task, build the toolbelt, get the configured LLMProvider,
and loop: run_turn -> execute any requested tool calls -> append results ->
repeat until the model returns a final response with no more tool calls.

There is no fixed sequence of steps here beyond that loop — which tools get
called, in what order, is entirely the model's decision (see
app/agent/system_prompt.py for the guidance it reasons from). This file must
never import `openai` or `anthropic` directly; it only talks to the
LLMProvider interface and the toolbelt's dispatcher.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.agent.llm import get_llm_provider
from app.agent.llm.base import Message
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import Toolbelt

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 15

WRITE_DRAFT_ENTRY_TOOL_NAME = "write_draft_entry"


@dataclass
class AgentRunResult:
    """Return value of `run_agent`.

    `created_entry_id` is the id of the draft entry created via
    `write_draft_entry` during this run, if any -- None if the tool was
    never called. Callers (e.g. the /agent/run endpoint) can hand this
    straight to the frontend instead of it having to guess which entry was
    just created via a separate follow-up query.
    """

    response_text: str
    created_entry_id: Optional[int] = None


async def run_agent(user_id: int, task: str) -> AgentRunResult:
    provider = get_llm_provider()

    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=task),
    ]

    created_entry_id: Optional[int] = None

    async with Toolbelt(user_id=user_id) as toolbelt:
        logger.info("Toolbelt assembled with %d tools.", len(toolbelt.tool_definitions))

        for round_number in range(1, MAX_TOOL_ROUNDS + 1):
            response = await provider.run_turn(messages, toolbelt.tool_definitions)

            if response.is_final:
                logger.info("Agent finished after %d tool-call round(s).", round_number - 1)
                return AgentRunResult(
                    response_text=response.text or "", created_entry_id=created_entry_id
                )

            messages.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )

            for tool_call in response.tool_calls:
                logger.info(
                    "[round %d] calling %s(%s)", round_number, tool_call.name, tool_call.arguments
                )
                result = await toolbelt.dispatch(tool_call)
                logger.info("[round %d] %s -> %s", round_number, tool_call.name, result)

                if (
                    tool_call.name == WRITE_DRAFT_ENTRY_TOOL_NAME
                    and isinstance(result, dict)
                    and result.get("entry_id") is not None
                ):
                    created_entry_id = result["entry_id"]

                messages.append(
                    Message(
                        role="tool",
                        content=json.dumps(result, default=str),
                        tool_call_id=tool_call.id,
                    )
                )

    # The round budget is spent, but the model's last move may have been a
    # tool call rather than a final answer -- its results are already in
    # `messages` above, just never shown back to the model for a verdict.
    # Force exactly one more call with tools disabled so it must synthesize
    # from whatever evidence was gathered instead of the loop just cutting
    # off and discarding it.
    logger.warning(
        "Exceeded MAX_TOOL_ROUNDS=%d; forcing a final synthesis-only turn with tools disabled.",
        MAX_TOOL_ROUNDS,
    )
    messages.append(
        Message(
            role="user",
            content=(
                "You've reached the maximum number of tool-call rounds for this task, "
                "and tools are now disabled. Using only the evidence already gathered "
                "in this conversation, give your best final answer now."
            ),
        )
    )
    final_response = await provider.run_turn(messages, [])
    return AgentRunResult(
        response_text=final_response.text or "[agent stopped: no usable evidence was gathered]",
        created_entry_id=created_entry_id,
    )
