from fastapi import FastAPI

from app.api import auth, entries, integrations, self_captures, timeline

app = FastAPI(title="Logline")

app.include_router(auth.router)
app.include_router(integrations.router)
app.include_router(entries.router)
app.include_router(timeline.router)
app.include_router(self_captures.router)


@app.get("/health")
def health():
    return {"status": "ok"}
