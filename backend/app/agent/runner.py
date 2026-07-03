from anthropic import Anthropic

from app.agent.system_prompt import SYSTEM_PROMPT
from app.config import settings

# Custom tool schemas + handlers live in app/agent/tools/. MCP servers
# (GitHub, Slack, Jira, Calendar) are wired in here as additional tools.
# The agent loop below decides which tools to call and when to stop —
# there is no separate pipeline module dictating the sequence of steps.

client = Anthropic(api_key=settings.anthropic_api_key)

MODEL = "claude-sonnet-5"


def run_agent(user_message: str, tools: list[dict], tool_handlers: dict) -> str:
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            return "".join(
                block.text for block in response.content if block.type == "text"
            )

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            handler = tool_handlers[block.name]
            result = handler(**block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})
