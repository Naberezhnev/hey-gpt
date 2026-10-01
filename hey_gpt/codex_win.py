"""Emergency hotkey; isolated from the browser UI Automation adapter."""
import ctypes
from ctypes import wintypes
import os


def emergency_pressed():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return all(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x50))


def process_alive(pid):
    if not pid:
        return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        # Access denied is not proof of termination.
        return ctypes.get_last_error() == 5
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def codex_parent_pid():
    """Follow the hook's parent chain, without reading command lines or tokens."""
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("name", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == wintypes.HANDLE(-1).value:
        return None
    try:
        entries = {}
        entry = Entry(size=ctypes.sizeof(Entry))
        present = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while present:
            entries[entry.pid] = (entry.parent, entry.name.casefold())
            present = kernel.Process32NextW(handle, ctypes.byref(entry))
        pid = os.getpid()
        for _ in range(16):
            parent, name = entries.get(pid, (0, ""))
            if pid != os.getpid() and name in ("codex.exe", "chatgpt.exe"):
                return pid
            if not parent or parent == pid:
                break
            pid = parent
        return None
    finally:
        kernel.CloseHandle(handle)
