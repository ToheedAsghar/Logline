import ctypes
import sys

from tracker.constants import VIP_PATH_OFFSET, VNODEPATHINFO_SIZE
from tracker.context import proc


class FakeLib:
    def __init__(self):
        self.children = [11, 12]

    def proc_listchildpids(self, pid, buffer, size):
        if buffer is None:
            return len(self.children)
        for index, child in enumerate(self.children):
            buffer[index] = child
        return len(self.children)

    def proc_pidinfo(self, pid, kind, flavor, buffer, size):
        if kind == proc.PROC_PIDVNODEPATHINFO:
            payload = b"/Users/test/project\0"
            ctypes.memmove(ctypes.addressof(buffer), b"\0" * VNODEPATHINFO_SIZE, VNODEPATHINFO_SIZE)
            ctypes.memmove(ctypes.addressof(buffer) + VIP_PATH_OFFSET, payload, len(payload))
        return size

    def sysctl(self, mib, mib_len, buffer, size_ptr, new, new_len):
        payload = (2).to_bytes(4, sys.byteorder) + b"/bin/codex\0codex\0--help\0"
        if buffer is None:
            size_ptr._obj.value = len(payload)
        else:
            size_ptr._obj.value = len(payload)
            ctypes.memmove(ctypes.addressof(buffer), payload, len(payload))
        return 0


def test_child_pids_reads_a_pid_count(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(proc, "_libs", lambda: (lib, None))
    assert proc.child_pids(10) == [11, 12]


def test_working_directory_uses_the_kernel_path_offset(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(proc, "_libs", lambda: (lib, None))
    assert proc.working_directory(10) == "/Users/test/project"


def test_bsd_info_returns_the_expected_structure(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(proc, "_libs", lambda: (lib, None))
    assert isinstance(proc.bsd_info(10), proc.ProcBsdInfo)


def test_exec_path_and_argv_decodes_kernel_arguments(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(proc, "_libs", lambda: (None, lib))
    assert proc.exec_path_and_argv(10) == ("/bin/codex", ["codex", "--help"])


def test_tty_foreground_requires_a_terminal_and_matching_groups():
    info = proc.ProcBsdInfo()
    info.e_tdev = 1
    info.pbi_pgid = 7
    info.e_tpgid = 7
    assert proc.is_tty_foreground(info)
    info.e_tpgid = 8
    assert not proc.is_tty_foreground(info)
