"""Direct test for app/db/session.py::get_db.

Every router calls db = SessionLocal() directly in this test suite (see
test_google_sso_callback.py's docstring), so the FastAPI dependency
generator itself is never exercised elsewhere. This confirms get_db rolls
back before closing when an exception escapes the request -- a review
flagged that a failed commit (e.g. crud.py's IntegrityError path) left
uncaught would otherwise return a connection to the pool without ever being
rolled back.
"""
import pytest

from app.db.session import get_db


def test_get_db_rolls_back_before_closing_on_exception():
    call_order = []
    gen = get_db()
    db = next(gen)

    original_rollback = db.rollback
    original_close = db.close

    def tracked_rollback():
        call_order.append("rollback")
        return original_rollback()

    def tracked_close():
        call_order.append("close")
        return original_close()

    db.rollback = tracked_rollback
    db.close = tracked_close

    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("simulated unhandled error mid-request"))

    assert call_order == ["rollback", "close"]


def test_get_db_closes_without_rollback_call_on_clean_exit():
    call_order = []
    gen = get_db()
    db = next(gen)

    db.rollback = lambda: call_order.append("rollback")
    original_close = db.close
    db.close = lambda: (call_order.append("close"), original_close())

    with pytest.raises(StopIteration):
        next(gen)

    assert call_order == ["close"]
