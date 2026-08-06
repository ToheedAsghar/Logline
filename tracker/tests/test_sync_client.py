"""SyncClient's response handling, exercised without a real backend.

`urlopen` is the only network seam, so mocking it covers the shape-validation contract: any parsed JSON that
isn't a dict must fail through `SyncError`, never propagate a bare `AttributeError` from a `.get()` call on a
list or string.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tracker.sync.client import SyncClient, SyncError

BASE_URL = "http://localhost:8000"
TOKEN = "tok-123"


def _fake_response(body) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(body).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestResponseShapeValidation:
    @pytest.mark.parametrize("body", [["a", "list"], "a string", 42, None])
    def test_get_checkpoint_rejects_non_dict_response(self, body):
        client = SyncClient(BASE_URL, TOKEN, timeout_seconds=5)
        with patch("tracker.sync.client.urlopen", return_value=_fake_response(body)):
            with pytest.raises(SyncError, match="unexpected response shape"):
                client.get_checkpoint()

    @pytest.mark.parametrize("body", [["a", "list"], "a string", 42, None])
    def test_post_sessions_rejects_non_dict_response(self, body):
        client = SyncClient(BASE_URL, TOKEN, timeout_seconds=5)
        with patch("tracker.sync.client.urlopen", return_value=_fake_response(body)):
            with pytest.raises(SyncError, match="unexpected response shape"):
                client.post_sessions("device-1", [])

    def test_a_well_shaped_response_still_works(self):
        client = SyncClient(BASE_URL, TOKEN, timeout_seconds=5)
        body = {"device_id": "d1", "last_synced_at": None}
        with patch("tracker.sync.client.urlopen", return_value=_fake_response(body)):
            checkpoint = client.get_checkpoint()

        assert checkpoint.device_id == "d1"
        assert checkpoint.last_synced_at is None
