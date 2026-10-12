"""Windows job object: child processes (ffmpeg) die when the app exits.

Without this, a blocked pipe or a timed-out wait leaves ffmpeg.exe (and
sometimes the frozen Broadcast.exe itself) sitting in Task Manager.
"""
from __future__ import annotations

import os
import sys

_HANDLE = None
_KERNEL32 = None

# Don't reap the shell we opened to reveal a folder.
_SKIP_NAMES = {"explorer.exe", "conhost.exe", "dllhost.exe"}


def _k32():
    global _KERNEL32
    if _KERNEL32 is None:
        import ctypes
        _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _KERNEL32


def attach_kill_on_close() -> None:
    """Put this process in a job that kills every child when our last handle dies."""
    global _HANDLE
    if os.name != "nt" or _HANDLE is not None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = _k32()
        JobObjectExtendedLimitInformation = 9
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(handle)
            return
        if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
            kernel32.CloseHandle(handle)
            return
        _HANDLE = handle
    except Exception:  # noqa: BLE001
        _HANDLE = None


def assign_pid(pid: int) -> None:
    """Attach a child PID to the kill-on-close job when the spawn missed it."""
    if os.name != "nt" or not _HANDLE or not pid:
        return
    try:
        import ctypes

        kernel32 = _k32()
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        PROCESS_SYNCHRONIZE = 0x0010
        access = PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SYNCHRONIZE
        proc = kernel32.OpenProcess(access, False, int(pid))
        if not proc:
            return
        try:
            kernel32.AssignProcessToJobObject(_HANDLE, proc)
        finally:
            kernel32.CloseHandle(proc)
    except Exception:  # noqa: BLE001
        pass


def _descendant_pids(root_pid: int) -> list[int]:
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = _k32()
        TH32CS_SNAPPROCESS = 0x00000002
        HANDLE = ctypes.c_void_p
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = HANDLE
        kernel32.Process32FirstW.argtypes = [HANDLE, ctypes.c_void_p]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [HANDLE, ctypes.c_void_p]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [HANDLE]

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        invalid = ctypes.c_void_p(-1).value
        if not snap or int(snap) in (0, -1) or int(snap) == invalid:
            return []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        children: dict[int, list[tuple[int, str]]] = {}
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            ppid = int(entry.th32ParentProcessID)
            name = (entry.szExeFile or "").lower()
            children.setdefault(ppid, []).append((pid, name))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        kernel32.CloseHandle(snap)

        out: list[int] = []
        stack = list(children.get(int(root_pid), []))
        while stack:
            pid, name = stack.pop()
            if name in _SKIP_NAMES:
                continue
            out.append(pid)
            stack.extend(children.get(pid, []))
        return out
    except Exception:  # noqa: BLE001
        return []


def kill_descendants() -> None:
    """Terminate ffmpeg and other children of this process."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = _k32()
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        PROCESS_TERMINATE = 0x0001
        for pid in _descendant_pids(os.getpid()):
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not handle:
                continue
            try:
                kernel32.TerminateProcess(handle, 1)
            finally:
                kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass


def hard_exit(code: int = 0) -> None:
    """Last-resort exit: reap children, then leave without Qt teardown."""
    kill_descendants()
    try:
        os._exit(code)
    except Exception:  # noqa: BLE001
        sys.exit(code)
