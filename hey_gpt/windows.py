"""Windows UI Automation adapter. Intentionally no coordinate-click fallback."""
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import time

import uiautomation as auto
from comtypes import COMError

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def title(hwnd):
    buffer = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


@dataclass
class Selector:
    control_type: str
    name: str
    automation_id: str

    @classmethod
    def capture(cls, control):
        value = cls(control.ControlTypeName, control.Name, control.AutomationId)
        if not value.name and not value.automation_id:
            raise RuntimeError("This element has no accessible name or ID.")
        return value

    def matches(self, control):
        return (control.ControlTypeName == self.control_type
                and control.Name == self.name
                and control.AutomationId == self.automation_id)


class WindowsAdapter:
    def __init__(self, selectors=None):
        self.selectors = {key: Selector(**value) for key, value in (selectors or {}).items()}
        self.hwnd = None
        self.window_title = ""

    def capture_at_cursor(self, role):
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("Cannot read cursor position.")
        hwnd = user32.GetAncestor(user32.WindowFromPoint(point), 2)
        name = title(hwnd)
        if not any(token in name.casefold() for token in ("chatgpt", "codex")):
            raise RuntimeError("Choose an open ChatGPT/Codex window whose title includes its name.")
        if self.hwnd and hwnd != self.hwnd:
            raise RuntimeError("All controls must belong to the same bound window. Rebind first.")
        self.hwnd, self.window_title = hwnd, name
        if role == "window":
            return name
        control = auto.ControlFromPoint(point.x, point.y)
        for _ in range(12):
            if control is None:
                break
            if role == "composer":
                if control.ControlTypeName == "EditControl":
                    break
            elif control.ControlTypeName == "ButtonControl":
                break
            control = control.GetParentControl()
        if control is None:
            raise RuntimeError("Could not find an accessible control under the cursor.")
        expected = "EditControl" if role == "composer" else "ButtonControl"
        if control.ControlTypeName != expected:
            raise RuntimeError("Choose an accessible " + expected + ".")
        self.selectors[role] = Selector.capture(control)
        # Prove the selector is unambiguous now; later it is resolved again.
        self.find(role)
        return self.selectors[role].name or self.selectors[role].automation_id

    def validate(self):
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            raise RuntimeError("Bind the target chat window first.")
        if user32.GetForegroundWindow() != self.hwnd:
            raise RuntimeError("The bound chat window must be in the foreground.")
        if title(self.hwnd) != self.window_title:
            raise RuntimeError("The active tab or window title changed. Rebind the intended chat.")

    def find(self, role, *, optional=False):
        self.validate()
        if role not in self.selectors:
            raise RuntimeError("Configure the " + role + " control first.")
        root = auto.ControlFromHandle(self.hwnd)
        stack = [(root, 0)]
        matches = []
        count = 0
        deadline = time.monotonic() + 3
        while stack:
            count += 1
            if count > 4000 or time.monotonic() > deadline:
                raise RuntimeError("The accessibility search exceeded its limit.")
            control, depth = stack.pop()
            try:
                if self.selectors[role].matches(control) and not control.IsOffscreen:
                    matches.append(control)
                    if len(matches) > 1:
                        raise RuntimeError("Ambiguous " + role + " control; recalibrate it.")
                if depth < 30:
                    stack.extend((child, depth + 1) for child in control.GetChildren())
            except COMError:
                continue
        if not matches:
            if optional:
                return None
            raise RuntimeError("The " + role + " control is not visible in the bound chat.")
        return matches[0]

    def click(self, role):
        control = self.find(role)
        if not control.IsEnabled:
            raise RuntimeError(role + " is disabled.")
        self.validate()
        # Invoke the accessible button; never guess screen coordinates.
        control.GetInvokePattern().Invoke()

    def read_text(self):
        control = self.find("composer")
        try:
            return control.GetValuePattern().Value
        except Exception:
            return control.GetTextPattern().DocumentRange.GetText(-1)

    def replace_text(self, expected, replacement):
        if self.read_text() != expected:
            raise RuntimeError("Composer changed while removing the stop command.")
        control = self.find("composer")
        self.validate()
        # A multiline browser editor may not expose ValuePattern. Fail closed;
        # leave the text for manual review instead of synthesizing keystrokes.
        control.GetValuePattern().SetValue(replacement)

    def recording_visible(self):
        return self.find("finish", optional=True) is not None

    def send_enabled(self):
        control = self.find("send", optional=True)
        return control is not None and control.IsEnabled

    def export(self):
        return {key: asdict(selector) for key, selector in self.selectors.items()}


def emergency_pressed():
    # Ctrl + Alt + P, checked even if this application's GUI is not focused.
    return all(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x50))
