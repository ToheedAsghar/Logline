from fastapi import FastAPI, Header, HTTPException
import time

app = FastAPI()

@app.get("/tracker/sync/checkpoint")
def get_checkpoint(authorization: str = Header(None)):
    if authorization != "Bearer valid_token":
        raise HTTPException(status_code=401, detail="Invalid token")
    time.sleep(10) # Simulate slow network for mid-flight sync test
    return {"device_id": "test_device_123", "last_synced_at": "2023-10-01T12:00:00Z"}
