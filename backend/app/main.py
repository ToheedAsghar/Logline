from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent import routers as agent
from app.agent.reconciliation import routers as reconciliation
from app.auth import routers as auth
from app.config import settings
from app.core.logging import configure_logging
from app.core.request_context import RequestIDMiddleware
from app.db import base  # noqa: F401
from app.entries import routers as entries
from app.integrations import routers as integrations
from app.self_captures import routers as self_captures
from app.timeline import routers as timeline
from app.tracker_sync import routers as tracker_sync

configure_logging()

app = FastAPI(title="Logline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)

app.include_router(auth.router)
app.include_router(integrations.router)
app.include_router(entries.router)
app.include_router(timeline.router)
app.include_router(self_captures.router)
app.include_router(agent.router)
app.include_router(reconciliation.router)
app.include_router(tracker_sync.router)
