"""Single-instance guard.

Two trackers running at once share one `open_session` row and overwrite each other's mirror: each `insert_open_session`
deletes the other's row, and each heartbeat UPDATE silently matches nothing once its row has been replaced. The
result is lost session boundaries rather than a visible error, so the second instance must refuse to start.
"""

import errno
import fcntl
import os
from pathlib import Path
from typing import Optional

from tracker.constants import LOCK_PATH


class AlreadyRunning(RuntimeError):
    """Another tracker already holds the lock. Carries that instance's pid when the lock file could be read, for a
    diagnosable message rather than a bare failure."""

    def __init__(self, pid: Optional[int]) -> None:
        self.pid = pid
        owner = f"pid {pid}" if pid is not None else "unknown pid"
        super().__init__(f"another tracker instance is already running ({owner})")


class SingleInstanceLock:
    """Exclusive whole-process lock, held for the tracker's lifetime.

    Backed by flock() rather than a bare pid file. The kernel releases an flock when the holding process dies —
    including on SIGKILL, and including a crash mid-write — so a crashed tracker can never strand a lock that blocks
    the restart its supervisor is about to perform. A pid file alone would need stale-entry detection, which races
    against pid reuse. The pid written into the file is diagnostic only; the lock is what enforces exclusion.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path if path is not None else LOCK_PATH
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        """Raises AlreadyRunning if another instance holds the lock."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            holder = self._read_pid(fd)
            os.close(fd)
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise AlreadyRunning(holder) from exc
            raise

        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)
        self._fd = fd

    @staticmethod
    def _read_pid(fd: int) -> Optional[int]:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 32).decode("utf-8", "replace").strip()
        except OSError:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def release(self) -> None:
        """Idempotent, so an exception during startup can't double-release."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> bool:
        self.release()
        return False
