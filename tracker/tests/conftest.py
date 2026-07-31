import sqlite3

import pytest

from tracker.constants import _CREATE_OPEN_SESSION, _CREATE_SESSIONS


@pytest.fixture
def conn():
    """An in-memory sqlite connection with the tracker schema, isolated from the
    real on-disk database at DB_PATH."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(_CREATE_SESSIONS)
    connection.execute(_CREATE_OPEN_SESSION)
    connection.commit()
    yield connection
    connection.close()


def all_sessions(connection):
    return [dict(row) for row in connection.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()]


def open_session_rows(connection):
    return [dict(row) for row in connection.execute("SELECT * FROM open_session").fetchall()]
