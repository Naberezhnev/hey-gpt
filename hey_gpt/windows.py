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
            raise RuntimeError("У элемента нет доступного имени или ID.")
        return value

    def matches(self, control):
        return (control.ControlTypeName == self.control_type
                and (control.AutomationId == self.automation_id if self.automation_id
                     else control.Name == self.name))


class WindowsAdapter:
    def __init__(self, selectors=None):
        self.selectors = {key: Selector(**value) for key, value in (selectors or {}).items()}
        self.hwnd = None
        self.window_title = ""

    def capture_at_cursor(self, role):
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("Не удалось определить положение курсора.")
        hwnd = user32.GetAncestor(user32.WindowFromPoint(point), 2)
        name = title(hwnd)
        if not any(token in name.casefold() for token in ("chatgpt", "codex")):
            raise RuntimeError("Выбери окно с ChatGPT или Codex в заголовке.")
        if role != "window" and self.hwnd and hwnd != self.hwnd:
            raise RuntimeError("Выбирай элементы в одном окне. Для смены окна начни с шага 1.")
        if role == "window":
            if self.hwnd is not None and self.hwnd != hwnd:
                self.selectors.clear()
            self.hwnd, self.window_title = hwnd, name
            return name
        if not self.hwnd:
            raise RuntimeError("Сначала выбери окно чата.")
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
            raise RuntimeError("Под курсором не найден доступный элемент.")
        expected = "EditControl" if role == "composer" else "ButtonControl"
        if control.ControlTypeName != expected:
            raise RuntimeError("Выбери поле сообщения." if role == "composer" else "Выбери кнопку.")
        selected = Selector.capture(control)
        previous = self.selectors.get(role)
        self.selectors[role] = selected
        # Prove the selector is unambiguous now; later it is resolved again.
        try:
            self.find(role, require_foreground=False)
        except Exception:
            if previous is None:
                self.selectors.pop(role, None)
            else:
                self.selectors[role] = previous
            raise
        return self.selectors[role].name or self.selectors[role].automation_id

    def validate(self, *, require_foreground=True):
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            raise RuntimeError("Сначала выбери окно чата.")
        if require_foreground and user32.GetForegroundWindow() != self.hwnd:
            raise RuntimeError("Вернись в выбранное окно чата; затем сбрось цикл.")
        if title(self.hwnd) != self.window_title:
            raise RuntimeError("Заголовок окна или вкладка изменились. Выбери нужное окно заново.")

    def find(self, role, *, optional=False, require_foreground=True):
        self.validate(require_foreground=require_foreground)
        if role not in self.selectors:
            raise RuntimeError("Сначала настрой элемент: " + role)
        root = auto.ControlFromHandle(self.hwnd)
        stack = [(root, 0)]
        matches = []
        count = 0
        deadline = time.monotonic() + 3
        while stack:
            count += 1
            if count > 4000 or time.monotonic() > deadline:
                raise RuntimeError("Поиск элементов занял слишком много времени. Попробуй отдельное окно чата.")
            control, depth = stack.pop()
            try:
                if self.selectors[role].matches(control) and not control.IsOffscreen:
                    matches.append(control)
                    if len(matches) > 1:
                        raise RuntimeError("Найдено несколько одинаковых элементов: " + role + ". Повтори настройку.")
                if depth < 30:
                    stack.extend((child, depth + 1) for child in control.GetChildren())
            except COMError:
                continue
        if not matches:
            if optional:
                return None
            raise RuntimeError("Элемент сейчас не виден: " + role)
        return matches[0]

    def click(self, role):
        control = self.find(role)
        if not control.IsEnabled:
            raise RuntimeError("Элемент недоступен: " + role)
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
            raise RuntimeError("Текст изменился во время удаления команды. Проверь черновик.")
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
