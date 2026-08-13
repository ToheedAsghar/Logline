"""The outgoing payload is an allowlist, and must stay one.

The failure this guards against is silent: a column added to the local `sessions` table for some new local-only
signal starts being uploaded because the payload was built by widening whatever the row happened to contain.
"""

import sqlite3

from tracker.sync.payload import ALLOWED_FIELDS, SyncSessionOut

ROW_VALUES = {
    "id": "1b9d2c3e-0000-4000-8000-000000000001",
    "bundle_id": "com.microsoft.VSCode",
    "app_name": "Code",
    "window_title": "db.py — logline",
    "started_at": "2026-08-06T14:00:00+05:00",
    "ended_at": "2026-08-06T14:05:00+05:00",
    "end_reason": "switch",
    "is_idle": 0,
    "project_path": "/Users/x/logline",
    "context_detail": '{"git_branch": "main"}',
}


def _select_row(values: dict) -> sqlite3.Row:
    """Builds a one-row result set with exactly `values` as its columns, so a row can carry columns the local
    schema does not have yet."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    columns = ", ".join(f"? AS {name}" for name in values)
    row = conn.execute(f"SELECT {columns}", tuple(values.values())).fetchone()
    conn.close()
    return row


def _row(**overrides) -> sqlite3.Row:
    return _select_row({**ROW_VALUES, **overrides})


class TestAllowlist:
    def test_payload_keys_are_exactly_the_allowlist(self):
        payload = SyncSessionOut.from_row(_row()).to_payload()
        assert set(payload) == set(ALLOWED_FIELDS)

    def test_extra_columns_on_the_row_are_not_transmitted(self):
        """A new local column must require a deliberate edit to this module before it can leave the machine."""
        widened = _select_row({**ROW_VALUES, "keystroke_log": "s3cret"})

        payload = SyncSessionOut.from_row(widened).to_payload()
        assert "keystroke_log" not in payload
        assert "s3cret" not in str(payload)

    def test_field_values_round_trip(self):
        payload = SyncSessionOut.from_row(_row()).to_payload()
        assert payload["window_title"] == ROW_VALUES["window_title"]
        assert payload["started_at"] == ROW_VALUES["started_at"]
        assert payload["context_detail"] == ROW_VALUES["context_detail"]


class TestTypeCoercion:
    def test_is_idle_becomes_a_bool(self):
        """SQLite stores 0/1; the backend schema is a bool and rejects an int with extra="forbid" semantics."""
        assert SyncSessionOut.from_row(_row(is_idle=1)).to_payload()["is_idle"] is True
        assert SyncSessionOut.from_row(_row(is_idle=0)).to_payload()["is_idle"] is False

    def test_nullable_fields_stay_none(self):
        payload = SyncSessionOut.from_row(_row(window_title=None, project_path=None, context_detail=None)).to_payload()
        assert payload["window_title"] is None
        assert payload["project_path"] is None
        assert payload["context_detail"] is None
