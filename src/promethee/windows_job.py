"""Windows kill-on-close job for an owned worker and all its descendants.

The worker waits for stdin; attach it before sending any request. This also
cleans up child processes after the worker itself exits unexpectedly.
"""

import ctypes
from ctypes import wintypes


class ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("priority", wintypes.LONG),
        ("delta", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD),
        ("working_min", ctypes.c_size_t),
        ("working_max", ctypes.c_size_t),
        ("active_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in ("reads", "writes", "others", "read_bytes", "write_bytes", "other_bytes")
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io", IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class WindowsJob:
    def __init__(self, process):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = ExtendedLimits()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)
        # CPython Popen owns this native process handle until process cleanup.
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def resume(self, pid):
        """Resume the sole initial thread after assigning CREATE_SUSPENDED to the job."""
        api = self.api
        api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ("Thread32First", "Thread32Next"):
            fn = getattr(api, name)
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
            fn.restype = wintypes.BOOL
        api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenThread.restype = wintypes.HANDLE
        api.ResumeThread.argtypes = [wintypes.HANDLE]
        api.ResumeThread.restype = wintypes.DWORD
        snapshot = api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.process_id == pid:
                    thread = api.OpenThread(2, False, entry.thread_id)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if api.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        api.CloseHandle(thread)
                    return
                found = api.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("The suspended worker's initial thread was not found.")
        finally:
            api.CloseHandle(snapshot)
