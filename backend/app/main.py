from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agent
from app.auth import routers as auth
from app.config import settings
# Registers every domain's models on Base.metadata before any request can
# trigger SQLAlchemy's configure_mappers() -- without this, a domain with no
# router importing its models (e.g. WorkBlock) would never get registered,
# and the first cross-domain relationship() lookup (e.g. User.work_blocks)
# would fail at request time.
from app.db import base  # noqa: F401
from app.entries import routers as entries
from app.integrations import routers as integrations
from app.self_captures import routers as self_captures
from app.timeline import routers as timeline

app = FastAPI(title="Logline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(integrations.router)
app.include_router(entries.router)
app.include_router(timeline.router)
app.include_router(self_captures.router)
app.include_router(agent.router)


@app.get("/health")
def health():
    return {"status": "ok"}
