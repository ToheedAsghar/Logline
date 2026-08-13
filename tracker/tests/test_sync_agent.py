"""The agent's run loop, exercised without launchd, a network, or a backend.

`SyncClient` is the only seam that touches the network, so a fake standing in for it covers batching, cursor
advance, drain-to-empty and the resume-from-checkpoint contract directly.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from tracker.constants import CREATE_OPEN_SESSION, CREATE_SESSIONS, SYNC_OVERLAP_SECONDS
from tracker.sync import reader
from tracker.sync.agent import read_device_token, run_sync
from tracker.sync.client import Checkpoint, SyncClient, SyncError

BASE = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)
DEVICE_ID = "1b9d2c3e-0000-4000-8000-000000000009"


class FakeClient:
    """Records what was sent. `fail_on_batch` makes the Nth batch raise, standing in for a dropped connection."""

    def __init__(self, last_synced_at=None, fail_on_batch=None):
        self._checkpoint = Checkpoint(device_id=DEVICE_ID, last_synced_at=last_synced_at)
        self._fail_on_batch = fail_on_batch
        self.batches = []
        self.device_ids = []

    def get_checkpoint(self):
        return self._checkpoint

    def post_sessions(self, device_id, sessions):
        self.device_ids.append(device_id)
        if self._fail_on_batch is not None and len(self.batches) == self._fail_on_batch:
            raise ConnectionError("connection reset")
        self.batches.append([s.id for s in sessions])
        return {"accepted": len(sessions), "duplicate": 0, "invalid": 0, "total": len(sessions)}

    @property
    def sent_ids(self):
        return [session_id for batch in self.batches for session_id in batch]


@pytest.fixture
def sessions_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE_SESSIONS)
    conn.execute(CREATE_OPEN_SESSION)
    conn.commit()
    yield conn
    conn.close()


def _insert(conn, session_id, ended_at):
    conn.execute(
        "INSERT INTO sessions (id, bundle_id, app_name, window_title, started_at, ended_at, end_reason, is_idle) "
        "VALUES (?, 'com.microsoft.VSCode', 'Code', 'db.py', ?, ?, 'switch', 0)",
        (session_id, ended_at, ended_at),
    )
    conn.commit()


def _seed(conn, count, start=BASE, spacing=timedelta(minutes=1)):
    for index in range(count):
        _insert(conn, f"s{index}", (start + spacing * index).isoformat())


class TestRunSync:
    def test_sends_everything_in_batches_oldest_first(self, sessions_conn):
        _seed(sessions_conn, 5)
        client = FakeClient()

        sent = run_sync(client, sessions_conn, batch_size=2)

        assert sent == 5
        assert client.batches == [["s0", "s1"], ["s2", "s3"], ["s4"]]

    def test_stops_when_the_backlog_is_drained(self, sessions_conn):
        """The loop must end on the first empty read rather than re-posting the tail."""
        _seed(sessions_conn, 3)
        client = FakeClient()

        run_sync(client, sessions_conn, batch_size=10)

        assert len(client.batches) == 1

    def test_nothing_new_is_a_no_op(self, sessions_conn):
        _seed(sessions_conn, 2)
        client = FakeClient(last_synced_at=BASE + timedelta(days=1))

        sent = run_sync(client, sessions_conn, batch_size=10)

        assert sent == 0
        assert client.batches == []

    def test_empty_database_is_a_no_op(self, sessions_conn):
        client = FakeClient()

        assert run_sync(client, sessions_conn, batch_size=10) == 0
        assert client.batches == []

    def test_resumes_from_the_server_checkpoint(self, sessions_conn):
        """Sessions older than the checkpoint minus the overlap window are not re-sent. Spaced by the overlap
        window itself so the expectation holds whatever that window is tuned to."""
        overlap = timedelta(seconds=SYNC_OVERLAP_SECONDS)
        _seed(sessions_conn, 5, spacing=overlap)
        client = FakeClient(last_synced_at=BASE + 4 * overlap)

        run_sync(client, sessions_conn, batch_size=10)

        assert client.sent_ids == ["s4"]

    def test_device_id_comes_from_the_server_not_local_state(self, sessions_conn):
        _seed(sessions_conn, 1)
        client = FakeClient()

        run_sync(client, sessions_conn, batch_size=10)

        assert client.device_ids == [DEVICE_ID]

    def test_a_failed_batch_stops_the_run_and_propagates(self, sessions_conn):
        """No retry loop here by design: the next scheduled run resumes from the server's checkpoint."""
        _seed(sessions_conn, 6)
        client = FakeClient(fail_on_batch=1)

        with pytest.raises(ConnectionError):
            run_sync(client, sessions_conn, batch_size=2)

        assert client.batches == [["s0", "s1"]]

    def test_a_rerun_after_a_failure_resends_from_the_checkpoint(self, sessions_conn):
        """The server checkpoint advanced only for the batch it accepted, so the rest is still pending."""
        _seed(sessions_conn, 6)
        failed = FakeClient(fail_on_batch=1)
        with pytest.raises(ConnectionError):
            run_sync(failed, sessions_conn, batch_size=2)

        resumed = FakeClient(last_synced_at=BASE + timedelta(minutes=1))
        run_sync(resumed, sessions_conn, batch_size=2)

        assert "s2" in resumed.sent_ids and "s5" in resumed.sent_ids

    def test_only_allowlisted_fields_are_posted(self, sessions_conn):
        _seed(sessions_conn, 1)

        posted = {}

        class CapturingClient(FakeClient):
            def post_sessions(self, device_id, sessions):
                posted.update(sessions[0].to_payload())
                return super().post_sessions(device_id, sessions)

        run_sync(CapturingClient(), sessions_conn, batch_size=10)

        assert set(posted) == set(reader.SyncSessionOut.__dataclass_fields__)

    def test_a_wrong_shaped_backend_response_fails_as_sync_error_not_attribute_error(self, sessions_conn):
        """A backend that returns valid-JSON-but-not-a-dict (a proxy quirk, a maintenance-mode responder) must
        surface as the same SyncError every other sync failure does -- not an AttributeError from `.get()` on a
        list, which `main()` does not catch and would let escape as a raw, unhandled traceback instead of the
        structured SYNC_FAILED_MSG logging path."""
        _seed(sessions_conn, 1)
        response = MagicMock()
        response.read.return_value = json.dumps(["unexpected", "shape"]).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        client = SyncClient("http://localhost:8000", "tok-123", timeout_seconds=5)

        with patch("tracker.sync.client.urlopen", return_value=response):
            with pytest.raises(SyncError, match="unexpected response shape"):
                run_sync(client, sessions_conn, batch_size=10)


class TestDeviceToken:
    def test_missing_file_reads_as_not_enrolled(self, tmp_path):
        assert read_device_token(tmp_path / "device_token") is None

    def test_empty_file_reads_as_not_enrolled(self, tmp_path):
        path = tmp_path / "device_token"
        path.write_text("   \n", encoding="utf-8")
        assert read_device_token(path) is None

    def test_token_is_stripped_of_trailing_newline(self, tmp_path):
        path = tmp_path / "device_token"
        path.write_text("tok-123\n", encoding="utf-8")
        assert read_device_token(path) == "tok-123"

    def test_loose_permissions_warn_but_still_sync(self, tmp_path, caplog):
        path = tmp_path / "device_token"
        path.write_text("tok-123\n", encoding="utf-8")
        path.chmod(0o644)

        with caplog.at_level("WARNING"):
            assert read_device_token(path) == "tok-123"

        assert "chmod 600" in caplog.text

    def test_correct_permissions_are_silent(self, tmp_path, caplog):
        path = tmp_path / "device_token"
        path.write_text("tok-123\n", encoding="utf-8")
        path.chmod(0o600)

        with caplog.at_level("WARNING"):
            read_device_token(path)

        assert caplog.text == ""
