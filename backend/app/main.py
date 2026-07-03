from fastapi import FastAPI

app = FastAPI(title="Logline")


@app.get("/health")
def health():
    return {"status": "ok"}
