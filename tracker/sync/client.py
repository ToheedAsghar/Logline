"""HTTP client for the backend's tracker endpoints.

stdlib `urllib.request` rather than requests/httpx, since the tracker venv carries no dependencies beyond pyobjc.
This module is the seam the agent's tests mock, so it holds no logic beyond building requests and parsing
responses -- retries included: the launchd interval is the retry.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tracker.sync.payload import SyncSessionOut

CHECKPOINT_PATH = "/tracker/sync/checkpoint"
SYNC_PATH = "/tracker/sync"

ERROR_BODY_LIMIT = 500


class SyncError(RuntimeError):
    """A request failed. The message never includes the request headers, so the device token cannot reach a log."""


@dataclass(frozen=True)
class Checkpoint:
    """The server's view of this device: who it thinks we are, and how far it has been synced.

    `device_id` comes from the server rather than local state so the token file stays the only thing the machine
    has to keep.
    """

    device_id: str
    last_synced_at: Optional[datetime]


class SyncClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(f"{self._base_url}{path}", data=data, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:ERROR_BODY_LIMIT]
            raise SyncError(f"{method} {path} returned {exc.code}: {detail}") from exc
        except URLError as exc:
            raise SyncError(f"{method} {path} could not reach {self._base_url}: {exc.reason}") from exc
        except (ValueError, OSError) as exc:
            raise SyncError(f"{method} {path} failed: {exc}") from exc

        if not isinstance(parsed, dict):
            raise SyncError(f"{method} {path} returned unexpected response shape: {type(parsed).__name__}")
        return parsed

    def get_checkpoint(self) -> Checkpoint:
        payload = self._request("GET", CHECKPOINT_PATH)
        raw = payload.get("last_synced_at")
        device_id = payload.get("device_id")
        if not device_id:
            raise SyncError(f"GET {CHECKPOINT_PATH} returned no device_id")
        return Checkpoint(
            device_id=str(device_id),
            last_synced_at=datetime.fromisoformat(raw) if raw else None,
        )

    def post_sessions(self, device_id: str, sessions: List[SyncSessionOut]) -> dict:
        """Sends one batch. Returns the server's per-batch counts (accepted/duplicate/invalid/total)."""
        body = {"device_id": device_id, "sessions": [session.to_payload() for session in sessions]}
        return self._request("POST", SYNC_PATH, body)
