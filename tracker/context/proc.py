"""Read-only process checks for children, terminal focus, working folders, and arguments.

The checks stay separate from the resolvers so the resolvers remain easy to test. Each function returns None or
[] on failure instead of raising. A poll must not stop just because a process ended during the walk.

This module never reads window titles. It only reads process facts from the kernel.
"""

import ctypes
import ctypes.util
import logging
import sys
from typing import List, Optional, Tuple

from tracker.constants import (
    BSDINFO_SIZE, CTL_KERN, KERN_PROCARGS2, NODEV, PROC_PIDTBSDINFO, PROC_PIDVNODEPATHINFO, VIP_PATH_OFFSET,
    VIP_PATH_SIZE, VNODEPATHINFO_SIZE,
)

logger = logging.getLogger(__name__)

NUL = b"\x00"

_libproc = None
_libc = None


def _libs():
    """Load libproc and libc once. Return (None, None) if either library is unavailable."""
    global _libproc, _libc
    if _libproc is None or _libc is None:
        try:
            _libproc = ctypes.CDLL(ctypes.util.find_library("proc"), use_errno=True)
            _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            _libproc.proc_listchildpids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
            _libproc.proc_listchildpids.restype = ctypes.c_int
        except (OSError, AttributeError, TypeError):
            logger.debug("libproc/libc unavailable; terminal tool detection disabled", exc_info=True)
            return None, None
    return _libproc, _libc


class ProcBsdInfo(ctypes.Structure):
    """The macOS `struct proc_bsdinfo` layout. Keep field order and widths unchanged.

    Note: these layouts and the PIDINFO constants are hard-coded for the current macOS ABI. An Apple update that
    changes struct proc_bsdinfo or vnodepathinfo will break this code or read garbage. This is a compatibility
    risk, not an exploitable vulnerability. (N5)
    """

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64), ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def child_pids(pid: int) -> List[int]:
    """Return the direct children of `pid`, or [] if the lookup fails.

    `proc_listchildpids` returns the number of pids, not a byte count. This differs from the similar
    `proc_listpids`; treating the result as bytes would make this feature silently return no processes.
    """
    libproc, _ = _libs()
    if libproc is None or pid < 0:
        return []
    try:
        capacity = libproc.proc_listchildpids(pid, None, 0)
        if capacity <= 0:
            return []
        buf = (ctypes.c_int32 * capacity)()
        count = libproc.proc_listchildpids(pid, buf, ctypes.sizeof(buf))
        if count <= 0:
            return []
        return [buf[i] for i in range(min(count, capacity)) if buf[i] > 0]
    except (OSError, ValueError):
        return []


def bsd_info(pid: int) -> Optional[ProcBsdInfo]:
    """Return BSD process info, including process groups and terminal data, or None if it cannot be read."""
    libproc, _ = _libs()
    if libproc is None or pid < 0:
        return None
    try:
        info = ProcBsdInfo()
        got = libproc.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), BSDINFO_SIZE)
        return info if got == BSDINFO_SIZE else None
    except (OSError, ValueError):
        return None


def is_tty_foreground(info: ProcBsdInfo) -> bool:
    """Return whether the process owns the terminal's foreground process group.

    The foreground process group is the group currently receiving terminal input. An idle shell waiting for a
    child has different group IDs; the process in front has matching group IDs.
    """
    return info.e_tdev != NODEV and info.pbi_pgid == info.e_tpgid


def working_directory(pid: int) -> Optional[str]:
    """Return the process's working folder from the kernel, or None if it cannot be read.

    The folder is never taken from a window title.
    """
    libproc, _ = _libs()
    if libproc is None or pid < 0:
        return None
    try:
        buf = (ctypes.c_char * VNODEPATHINFO_SIZE)()
        got = libproc.proc_pidinfo(pid, PROC_PIDVNODEPATHINFO, 0, buf, VNODEPATHINFO_SIZE)
        if got != VNODEPATHINFO_SIZE:
            return None
        raw = bytes(buf[VIP_PATH_OFFSET:VIP_PATH_OFFSET + VIP_PATH_SIZE])
        return raw.split(NUL, 1)[0].decode("utf-8", "replace") or None
    except (OSError, ValueError):
        return None


def exec_path_and_argv(pid: int) -> Tuple[Optional[str], List[str]]:
    """Return the executable path and arguments for `pid` so they can be matched against the tool registry.

    Arguments can contain secrets, so they stay inside the matcher. Only the registry's standard tool name is
    recorded.
    """
    _, libc = _libs()
    if libc is None or pid < 0:
        return None, []
    try:
        mib = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid)
        size = ctypes.c_size_t(0)
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or size.value < 4:
            return None, []
        buf = (ctypes.c_char * size.value)()
        if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
            return None, []
        raw = bytes(buf[:size.value])
        argc = int.from_bytes(raw[:4], sys.byteorder)
        if argc <= 0:
            return None, []
        exec_path, _, rest = raw[4:].partition(NUL)
        argv = [part.decode("utf-8", "replace") for part in rest.lstrip(NUL).split(NUL)[:argc]]
        return exec_path.decode("utf-8", "replace") or None, argv
    except (OSError, ValueError):
        return None, []
