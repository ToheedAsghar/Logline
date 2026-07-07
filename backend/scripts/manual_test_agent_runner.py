"""Standalone script (not pytest) exercising the full agent runner loop
end-to-end: real MCP servers (GitHub, Slack, Jira, Calendar) plus the custom
tools (get_existing_events, write_event, flag_gap), orchestrated by
app.agent.runner.run_agent with no fixed pipeline — the agent decides which
tools to call and when to stop.

Requires OPENAI_API_KEY set in `backend/.env`, Docker running (GitHub/Jira
MCP servers), and Node/npx available (Slack/Calendar MCP servers). Run from
`backend/` with the venv active and Postgres up:

    python scripts/manual_test_agent_runner.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.runner import run_agent
from app.db.session import SessionLocal
from app.models.user import User

TEST_EMAIL = "agent-runner-test@example.com"
TASK = "What did I work on today?"


def get_or_create_test_user() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"[setup] created test user id={user.id}")
        else:
            print(f"[setup] reusing existing test user id={user.id}")
        return user.id
    finally:
        db.close()


async def main() -> None:
    user_id = get_or_create_test_user()
    print(f"\n[task] user_id={user_id} task={TASK!r}\n")

    final_response = await run_agent(user_id=user_id, task=TASK)

    print("\n=== FINAL AGENT RESPONSE ===")
    print(final_response)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
