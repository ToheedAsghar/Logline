"""Single-instance guard. The property under test is that a second tracker cannot start while a first one lives, and
— just as important — that it *can* start once the first one dies however abruptly, so a crash never leaves the
supervisor unable to restart."""

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from tracker.singleton import AlreadyRunning, SingleInstanceLock


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "tracker.lock"


def test_acquire_records_own_pid(lock_path):
    with SingleInstanceLock(lock_path) as lock:
        assert lock_path.read_text().strip() == str(os.getpid())
        assert lock.path == lock_path


def test_second_instance_is_refused(lock_path):
    with SingleInstanceLock(lock_path):
        with pytest.raises(AlreadyRunning) as excinfo:
            SingleInstanceLock(lock_path).acquire()
    # The holder's pid is reported so the failure is diagnosable rather than bare.
    assert excinfo.value.pid == os.getpid()
    assert "already running" in str(excinfo.value)


def test_refusal_leaves_holders_pid_intact(lock_path):
    """A rejected acquire must not truncate the file it failed to lock — otherwise the running instance's recorded pid
    is lost and the next failure reports nothing."""
    with SingleInstanceLock(lock_path):
        with pytest.raises(AlreadyRunning):
            SingleInstanceLock(lock_path).acquire()
        assert lock_path.read_text().strip() == str(os.getpid())


def test_lock_is_reusable_after_release(lock_path):
    first = SingleInstanceLock(lock_path)
    first.acquire()
    first.release()
    second = SingleInstanceLock(lock_path)
    second.acquire()  # must not raise
    second.release()


def test_release_is_idempotent(lock_path):
    lock = SingleInstanceLock(lock_path)
    lock.acquire()
    lock.release()
    lock.release()  # must not raise or close an unrelated fd


def test_missing_parent_directory_is_created(tmp_path):
    nested = tmp_path / "does" / "not" / "exist" / "tracker.lock"
    with SingleInstanceLock(nested):
        assert nested.exists()


def _spawn_holder(lock_path):
    """A child process that takes the lock and then blocks, so the parent can kill it."""
    source = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(_repo_root())!r})
        from pathlib import Path
        from tracker.singleton import SingleInstanceLock
        lock = SingleInstanceLock(Path({str(lock_path)!r}))
        lock.acquire()
        print("held", flush=True)
        time.sleep(60)
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", source], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "held"
    return child


def _repo_root():
    import tracker

    return os.path.dirname(os.path.dirname(os.path.abspath(tracker.__file__)))


def test_sigkilled_holder_does_not_strand_the_lock(lock_path):
    """The crash case the supervisor depends on: flock is released by the kernel when the holder dies, so a SIGKILLed
    tracker leaves nothing behind that would block the restart. A bare pid file would need stale-entry detection here,
    which races against pid reuse."""
    child = _spawn_holder(lock_path)
    try:
        with pytest.raises(AlreadyRunning):
            SingleInstanceLock(lock_path).acquire()

        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)

        # The pid of the dead holder is still written in the file; only the flock matters.
        deadline = time.monotonic() + 5
        while True:
            try:
                lock = SingleInstanceLock(lock_path)
                lock.acquire()
                lock.release()
                break
            except AlreadyRunning:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
